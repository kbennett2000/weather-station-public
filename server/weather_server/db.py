"""SQLite layer for logged readings.

Two tables, WAL mode. The CREATE TABLE statements below are the canonical
schema (an earlier docs/design/03-schema.md described it, but that design
doc was deleted post-rebuild). All conversions to derived values happen in
derivations/ at request time.

`outdoor_readings` holds the local ESP32 time series. `external_readings`
holds observations from the optional internet feed and is only ever
written when [external] is enabled — see ADR-0003. The two are kept
separate so a local sensor row never carries an internet-sourced value,
which is the provenance rule ADR-0001 and ADR-0002 established.

This module uses Python's stdlib sqlite3. Connections are not pooled: the
logger writes from one async task, request handlers read. SQLite + WAL
handles that pattern fine; `check_same_thread=False` is the only knob we
need so the event-loop thread can share a connection between the logger
task and the route handlers.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS outdoor_readings (
    id                  INTEGER PRIMARY KEY,
    timestamp           INTEGER NOT NULL,

    temperature_c       REAL,
    humidity_pct        REAL,
    pressure_pa         REAL,

    lux                 REAL,
    ir                  INTEGER,
    visible             INTEGER,
    full_spectrum       INTEGER,

    latitude            REAL,
    longitude           REAL,
    altitude_m          REAL,
    satellites          INTEGER,
    speed_kmh           REAL,
    course_deg          REAL,

    rssi_dbm            INTEGER,
    uptime_s            INTEGER,
    free_heap_bytes     INTEGER
);

CREATE INDEX IF NOT EXISTS idx_outdoor_readings_timestamp
    ON outdoor_readings (timestamp);
"""

# Added in schema v2 (ADR-0003). Kept as its own constant so it can serve
# both the fresh-database path and the v1 -> v2 migration step.
EXTERNAL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS external_readings (
    id                  INTEGER PRIMARY KEY,
    timestamp           INTEGER NOT NULL,

    observed_at         INTEGER,
    provider            TEXT NOT NULL,
    source              TEXT,
    station_id          TEXT,
    distance_km         REAL,

    wind_speed_ms       REAL,
    wind_gust_ms        REAL,
    wind_direction_deg  REAL,

    cloud_cover_pct     REAL,
    uv_index            REAL,
    precip_mm           REAL,
    visibility_m        REAL,

    confidence          TEXT
);

CREATE INDEX IF NOT EXISTS idx_external_readings_timestamp
    ON external_readings (timestamp);

-- Dedup guard. The fetch loop runs every ~300s but providers update far
-- more slowly, so the same observation is seen repeatedly. One row per
-- provider per observation instant, enforced by the DB rather than by a
-- read-before-write in the task.
CREATE UNIQUE INDEX IF NOT EXISTS idx_external_readings_unique
    ON external_readings (provider, timestamp);
"""

PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
)


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Open the DB, apply pragmas, ensure schema, return the connection.

    Safe to call repeatedly; uses CREATE IF NOT EXISTS.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        conn.execute(pragma)
    conn.executescript(SCHEMA_SQL)
    conn.executescript(EXTERNAL_SCHEMA_SQL)
    current_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if current_version == 0:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    elif current_version < SCHEMA_VERSION:
        _migrate(conn, current_version)
    elif current_version > SCHEMA_VERSION:
        raise RuntimeError(
            f"DB schema version mismatch: file has {current_version}, "
            f"code expects {SCHEMA_VERSION}. Downgrade is not supported — "
            f"restore a database file written by this version."
        )
    log.info("db opened at %s (schema v%s)", db_path, SCHEMA_VERSION)
    return conn


# Forward-only migration ladder. Every step must be idempotent DDL: the
# connection runs in autocommit and sqlite3.executescript() issues an
# implicit COMMIT, so wrapping a step in a transaction would not do what it
# looks like it does. Idempotence is the guarantee instead — if the process
# dies between the DDL and the user_version bump, the next start simply
# re-runs harmless CREATE ... IF NOT EXISTS.
MIGRATIONS: dict[int, str] = {
    2: EXTERNAL_SCHEMA_SQL,  # ADR-0003: log the optional external feed
}


def _migrate(conn: sqlite3.Connection, from_version: int) -> None:
    """Step an existing file up to SCHEMA_VERSION.

    No migration to date moves, alters or drops data — they only add tables
    and indexes.
    """
    for target in range(from_version + 1, SCHEMA_VERSION + 1):
        sql = MIGRATIONS.get(target)
        if sql is None:
            raise RuntimeError(f"no migration defined for schema v{target}")
        log.info("migrating db schema v%s -> v%s", target - 1, target)
        conn.executescript(sql)
        conn.execute(f"PRAGMA user_version = {target}")


OUTDOOR_COLUMNS = (
    "timestamp",
    "temperature_c",
    "humidity_pct",
    "pressure_pa",
    "lux",
    "ir",
    "visible",
    "full_spectrum",
    "latitude",
    "longitude",
    "altitude_m",
    "satellites",
    "speed_kmh",
    "course_deg",
    "rssi_dbm",
    "uptime_s",
    "free_heap_bytes",
)


def insert_outdoor_reading(
    conn: sqlite3.Connection,
    timestamp: int,
    payload: dict[str, Any],
) -> int:
    """Insert one row. Returns the rowid.

    `payload` is a SensorPayload-shaped dict (the same shape the fixture files
    use). Any column not present in the payload is stored as NULL.
    """
    values = [timestamp] + [payload.get(c) for c in OUTDOOR_COLUMNS[1:]]
    placeholders = ", ".join("?" for _ in OUTDOOR_COLUMNS)
    cols = ", ".join(OUTDOOR_COLUMNS)
    cur = conn.execute(
        f"INSERT INTO outdoor_readings ({cols}) VALUES ({placeholders})",
        values,
    )
    return cur.lastrowid or 0


def latest_outdoor_reading(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Return the most recent row, or None if the table is empty."""
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM outdoor_readings ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    return row


def outdoor_readings_in_range(
    conn: sqlite3.Connection,
    from_ts: int,
    to_ts: int,
) -> list[sqlite3.Row]:
    """Return raw rows in [from_ts, to_ts], ordered ascending."""
    rows = conn.execute(
        "SELECT * FROM outdoor_readings "
        "WHERE timestamp BETWEEN ? AND ? "
        "ORDER BY timestamp ASC",
        (from_ts, to_ts),
    ).fetchall()
    return list(rows)


def db_ok(conn: sqlite3.Connection) -> bool:
    """Cheap liveness probe used by /api/v1/health."""
    try:
        conn.execute("SELECT 1").fetchone()
        return True
    except sqlite3.Error:
        log.exception("db liveness probe failed")
        return False


def latest_outdoor_timestamp(conn: sqlite3.Connection) -> int | None:
    """Used by /api/v1/health to report how stale the outdoor logger is."""
    row = conn.execute(
        "SELECT timestamp FROM outdoor_readings ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    return int(row[0]) if row else None


EXTERNAL_COLUMNS = (
    "timestamp",
    "observed_at",
    "provider",
    "source",
    "station_id",
    "distance_km",
    "wind_speed_ms",
    "wind_gust_ms",
    "wind_direction_deg",
    "cloud_cover_pct",
    "uv_index",
    "precip_mm",
    "visibility_m",
    "confidence",
)


def insert_external_reading(
    conn: sqlite3.Connection,
    timestamp: int,
    values: dict[str, Any],
) -> bool:
    """Insert one external observation. Returns True if a row was written.

    Duplicates are dropped by the UNIQUE(provider, timestamp) index rather
    than by a read-before-write, which keeps the whole thing atomic. False
    means "we have already logged this observation", not an error.

    Note: lastrowid is unreliable with INSERT OR IGNORE, so this reports
    rowcount instead of a rowid.
    """
    row = dict(values)
    row["timestamp"] = timestamp
    cols = ", ".join(EXTERNAL_COLUMNS)
    placeholders = ", ".join("?" for _ in EXTERNAL_COLUMNS)
    cur = conn.execute(
        f"INSERT OR IGNORE INTO external_readings ({cols}) VALUES ({placeholders})",
        [row.get(c) for c in EXTERNAL_COLUMNS],
    )
    return bool(cur.rowcount)


def external_readings_in_range(
    conn: sqlite3.Connection,
    from_ts: int,
    to_ts: int,
) -> list[sqlite3.Row]:
    """Return external rows in [from_ts, to_ts], ordered ascending."""
    rows = conn.execute(
        "SELECT * FROM external_readings "
        "WHERE timestamp BETWEEN ? AND ? "
        "ORDER BY timestamp ASC",
        (from_ts, to_ts),
    ).fetchall()
    return list(rows)


def latest_external_reading(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Most recent external row, or None if the feed has never been logged."""
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM external_readings ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    return row
