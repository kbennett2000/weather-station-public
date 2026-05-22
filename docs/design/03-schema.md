# Weather Station Database Schema — SQLite

Status: draft for review
Date: 2026-05-22
Scope: SQLite schema for the weather station server. Greenfield design; the existing MariaDB tables are not migrated.

---

## Decisions feeding into this design

These were settled in prior conversations and are recorded here for reference:

| Decision | Choice | Why |
|---|---|---|
| Storage engine | SQLite (single-file, WAL mode) | Workload is append + range-scan; no separate service to manage; smaller RAM footprint on Pi; backups are a file copy |
| Migration approach | Greenfield, no import from MariaDB | Old data is expendable per the project owner |
| What is logged | Outdoor sensor only | Indoor and basement sensors remain live-only |
| Storage philosophy | Raw readings only; derivations computed server-side at read time | Bug fixes apply retroactively to history; schema doesn't change when new derived values are added |
| Pressure storage | Raw station pressure, in Pa | SI unit; matches what the BME280 actually reports |
| Timestamp storage | Unix epoch seconds (INTEGER), UTC | Fast comparisons, compact, formatting is the API's job |
| Calibration | Stored in TOML config, applied by API at read time | DB does not carry per-row calibration metadata |

Indoor and basement sensors are still polled live by the API server for `/api/v1/current`, but no history is retained for them. If a consumer asks for `/api/v1/history/indoor`, the API returns 404.

---

## The schema

```sql
-- Schema version. Increment when a migration is required.
PRAGMA user_version = 1;

-- Recommended runtime pragmas (set at every connection open).
-- These are listed here for documentation; they're not part of the schema.
-- PRAGMA journal_mode = WAL;
-- PRAGMA synchronous = NORMAL;
-- PRAGMA foreign_keys = ON;
-- PRAGMA busy_timeout = 5000;

CREATE TABLE outdoor_readings (
    id                  INTEGER PRIMARY KEY,        -- rowid alias, auto-assigned
    timestamp           INTEGER NOT NULL,            -- Unix epoch seconds, UTC

    -- Weather core (BME280)
    temperature_c       REAL,                        -- Raw, pre-calibration
    humidity_pct        REAL,
    pressure_pa         REAL,                        -- Station pressure, in Pascals

    -- Light (TSL2591)
    lux                 REAL,
    ir                  INTEGER,
    visible             INTEGER,
    full_spectrum       INTEGER,                     -- "full" is a SQL reserved word in some contexts

    -- GPS (NEO-6M)
    latitude            REAL,
    longitude           REAL,
    altitude_m          REAL,
    satellites          INTEGER,
    speed_kmh           REAL,
    course_deg          REAL,

    -- Device telemetry (ESP32)
    rssi_dbm            INTEGER,
    uptime_s            INTEGER,
    free_heap_bytes     INTEGER
);

-- Range-scan index for history queries.
CREATE INDEX idx_outdoor_readings_timestamp ON outdoor_readings (timestamp);
```

That's the whole schema. One table, sixteen data columns plus `id` and `timestamp`, one index.

---

## Field-by-field

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | INTEGER PK | no | SQLite rowid alias. Auto-assigned by `INSERT`. |
| `timestamp` | INTEGER | no | Unix epoch seconds in UTC. Set by the logger at insert time. |
| `temperature_c` | REAL | yes | Raw BME280 reading, in °C. **No calibration applied.** Offset lives in TOML config and is applied by the API. |
| `humidity_pct` | REAL | yes | 0–100. |
| `pressure_pa` | REAL | yes | Station pressure (at sensor altitude) in Pascals. All conversions (hPa, inHg, sea-level adjustment) happen in the API. |
| `lux` | REAL | yes | TSL2591 computed lux. Can be `null` if sensor was saturated or unreachable. |
| `ir` | INTEGER | yes | TSL2591 IR channel raw count. |
| `visible` | INTEGER | yes | Derived visible-light count (`full_spectrum - ir`). |
| `full_spectrum` | INTEGER | yes | TSL2591 full-spectrum channel raw count. Named `full_spectrum` rather than `full` to avoid the reserved-word risk in `SELECT full FROM ...`. |
| `latitude` | REAL | yes | Decimal degrees. `null` when GPS has no fix. |
| `longitude` | REAL | yes | Decimal degrees. |
| `altitude_m` | REAL | yes | Meters above sea level, from GPS. Used by the API for sea-level pressure adjustment. |
| `satellites` | INTEGER | yes | Count of satellites in the fix. |
| `speed_kmh` | REAL | yes | Should be ~0 for a fixed station; useful for diagnostics. |
| `course_deg` | REAL | yes | 0–360, true north. Diagnostic. |
| `rssi_dbm` | INTEGER | yes | WiFi signal strength as reported by ESP32. |
| `uptime_s` | INTEGER | yes | ESP32 uptime in seconds. The current sketch reports `millis()` (milliseconds); the logger divides by 1000 before insert. |
| `free_heap_bytes` | INTEGER | yes | ESP32 free heap. Useful for spotting memory leaks. |

All measurement columns are nullable because any individual sensor can fail independently. The logger writes a row whenever any meaningful weather data is available; missing values are stored as `NULL`, not as sentinel values like `-999` or `0`.

The `temperature_f` column from the old MariaDB schema is gone. It was a unit conversion of `temperature_c` — exactly the kind of derived value that now lives in the API, not the DB.

---

## Indexes

The only index is on `timestamp`. Justification:

- The only query pattern is `WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp` (history endpoint) and `ORDER BY timestamp DESC LIMIT 1` (current reading).
- `id` is implicitly indexed (it's the primary key / rowid).
- No JOINs, no filtering on other columns.

For a year of one-minute polling (~525,600 rows), the timestamp index is under 10 MB and range queries take single-digit milliseconds. No further tuning needed at this scale.

---

## Pragmas

The server should set the following pragmas on every connection:

```sql
PRAGMA journal_mode = WAL;       -- Concurrent readers + writers
PRAGMA synchronous = NORMAL;     -- Good safety/speed tradeoff for our case
PRAGMA foreign_keys = ON;        -- Future-proofing in case we add joined tables
PRAGMA busy_timeout = 5000;      -- Wait up to 5s for locks before giving up
```

**`journal_mode = WAL`** is the most important one. It allows the API server to read from the DB while the logger is writing, without either blocking the other. The alternative (rollback journal mode, the default) serializes all access. WAL also makes writes faster, which matters on slow SD cards.

**`synchronous = NORMAL`** in combination with WAL is the recommended sweet spot per the SQLite docs. `FULL` is overkill for time-series weather data where losing the last second of readings on power loss is not a disaster. `OFF` is too aggressive — risks DB corruption on power loss.

**`busy_timeout = 5000`** prevents transient lock errors from surfacing as application failures. SQLite normally returns `SQLITE_BUSY` immediately if a write is in progress; with the timeout, it retries internally for up to 5 seconds.

---

## Schema versioning

`PRAGMA user_version` is a built-in 4-byte integer stored in the database header, specifically intended for application-defined schema versioning. Current value: **1**.

When a future schema change is needed:

1. The server reads `PRAGMA user_version` at startup.
2. If the value is less than the version the code expects, run migrations in order.
3. After each successful migration, bump `user_version`.

This avoids the need for a separate `schema_migrations` table at this scale. If migrations ever get complex enough to need ordering/history tracking, the user_version pragma is still the gatekeeper but the actual migration log moves into a real table.

---

## Backup

The whole database is one file. Two viable backup strategies:

1. **Cold copy.** Stop the logger and API server, `cp readings.db readings.db.bak`, restart. Trivial, but requires downtime.

2. **Hot backup via SQLite's online backup API.** Most SQLite drivers (including Python's `sqlite3`) expose `Connection.backup()`. Atomic snapshot while the DB is live.

For a hobby weather station, a daily cron job invoking the Python `Connection.backup()` and rotating the last N copies is sufficient. The whole DB after a year of operation is well under 100 MB, so storing a week of daily backups costs nothing on a Pi SD card.

---

## Retention

This addresses **ARCH-08** from the findings list.

The schema does not enforce retention. The default behavior is: keep everything forever. At 1 reading/minute, the row count and disk use grow linearly:

| Duration | Rows | Approx DB size |
|---|---|---|
| 1 day | 1,440 | < 1 MB |
| 1 month | 43,200 | ~5 MB |
| 1 year | 525,600 | ~60 MB |
| 5 years | 2,628,000 | ~300 MB |

On a typical Pi SD card with several gigabytes free, "forever" is a long time. No retention enforcement is needed for the foreseeable life of the deployment.

If retention does become a concern (or the user prefers a fixed footprint), the recommended approach is a periodic `DELETE FROM outdoor_readings WHERE timestamp < ?` driven by a `retention_days` value in the TOML config. A nightly `VACUUM` reclaims the freed space.

Downsampling (keeping 1-minute resolution for 30 days, 5-minute for 6 months, hourly forever) is a possible future enhancement but the complexity is not justified at this scale.

---

## How this connects to the rest of the system

**Logger side.** The logger process polls the outdoor ESP32 at the configured interval (default 60 s), parses the JSON, and writes a single row to `outdoor_readings`. The same logger does not write anything for indoor or basement sensors. If the outdoor sensor is unreachable, no row is written for that interval — gaps in the timestamp series are legitimate signals of sensor downtime, not noise to be filled.

**API side.** The API server opens the DB read-only (or with WAL, simply read-mostly) at startup and keeps the connection open. Two access patterns:

- `/api/v1/current` for outdoor: `SELECT * FROM outdoor_readings ORDER BY timestamp DESC LIMIT 1`. Combined with the live poll of indoor/basement sensors, this is the data feeding the entire current-conditions view.
- `/api/v1/history/outdoor`: range scan with optional bucketing aggregated in SQL (`AVG()`, `GROUP BY (timestamp / ?)`).

**Indoor and basement sensors.** Not in the DB at all. The API server polls them live for `/api/v1/current`. If they're offline, the API returns the sensor object with `online: false` and no historical fallback (there's nothing to fall back to). Consumers display "no data" for those sensors when they're down.

---

## Changes to the rest of the system implied by this schema

1. **`/api/v1/history/{sensor_id}`** returns `404` for any `sensor_id` other than `outdoor`. The API design doc needs a one-line clarification.
2. **`/api/v1/sensors`** still lists all three sensors, but adds a per-sensor `logged: bool` field so consumers know whether history is available.
3. **`/api/v1/health.loggers`** has exactly one entry (`outdoor`), not three.
4. **The dashboard** loses its indoor and basement history charts. Current-conditions display for those sensors stays.
5. **README** needs updating to reflect that only outdoor data is retained. This also resolves the over-claim portion of **BUG-12** (the basement sensor's status moves from "half-implemented" to "intentionally live-only").

---

## Open items

None. Schema can be implemented as-is.

The next decisions in the implementation queue:

1. Logger redesign — single Python process polling outdoor (and optionally indoor/basement, write-discarded, for liveness only? Or does the API server poll them directly?).
2. Server module layout — derivation functions, sensor poll abstraction, route handlers.
3. Dashboard rewrite — what stays, what goes, what gets simpler.

These are independent of the schema and can be tackled in any order.
