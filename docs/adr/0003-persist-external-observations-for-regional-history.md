# 0003. Persist external observations so the regional series has history

Date: 2026-08-19
Status: Accepted

## Context

A request to chart wind speed alongside the other historical readings ran into a
wall: **there is no wind history to chart, and never has been.**

The station has no anemometer (ADR-0001 explains why, and why that is a deliberate
choice rather than an omission). Wind arrives only from the optional `[external]`
internet feed. That feed's entire storage is `external/store.py` — a 29-line
in-memory holder for the single most recent observation, with no TTL and no
history. `external/task.py` fetched on a timer, called `store.set(...)`, and wrote
nothing to disk. Every restart discarded everything the feed had ever seen.

So `/api/v1/current` could always answer "what is the wind right now", and nothing
could ever answer "what was the wind this morning".

Two related requests — absolute humidity and density altitude — needed no such
work. Both are derived from `temperature_c`, `humidity_pct` and `pressure_pa`,
all of which are logged columns, and `build_history_row` was already computing
them per bucket and discarding them. Those two shipped as an include-group change
and are retroactive over every row ever logged. Only wind required a decision.

The decision is genuinely load-bearing because of a locked project decision:

> **Logged data:** outdoor sensor only. Indoor and basement are live-only.

## Decision

**Log external observations to their own SQLite table, gated on `[external].enabled`,
and serve them from their own endpoint into their own dashboard panel.**

Specifically:

1. **A separate `external_readings` table**, not columns on `outdoor_readings`.
   Storage stays SI (`wind_speed_ms`); display units are derived at read time, per
   the existing "DB stores raw readings only" rule. Every field the provider
   returns is persisted — wind, gust, direction, cloud, UV, precip, visibility —
   because the marginal cost is a handful of nullable REALs on a table written at
   most a few times an hour, and the alternative is another schema bump the first
   time someone wants a cloud-cover chart.

2. **Dedup by `UNIQUE(provider, timestamp)` + `INSERT OR IGNORE`**, where
   `timestamp` is the provider's own `observed_at` when it supplies one. The fetch
   loop runs every ~300s but providers update far more slowly — NWS stations and
   Open-Meteo model output are both roughly hourly — so writing unconditionally
   would produce a dozen identical rows an hour and a chart implying a sample rate
   that does not exist. Enforcing this in the DB keeps it atomic and avoids a
   read-before-write in the task.

3. **A new endpoint, `GET /api/v1/external/history`**, under the `external`
   prefix. It answers `200` with `enabled: false` and an empty series when the
   feed is off, rather than `404`.

4. **A new dashboard panel, `HIST · D2 — Regional History`**, separate from
   `HIST · D1`, which names its provider and hides entirely when the feed is off.

5. **The project's first schema migration.** `SCHEMA_VERSION` goes 1 → 2 and
   `init_db` gained a forward-only `MIGRATIONS` ladder.

## Alternatives considered

**Columns on `outdoor_readings`.** Rejected. An internet-model value inside a row
labelled "what the ESP32 reported" is the same class of ambiguity as BUG-21, which
is the bug that produced the four-field pressure rule. The cadences also differ
(60s logger vs 300s feed), so four of every five rows would be null-filled, and
"disable the feed" would stop meaning "stop writing".

**`GET /api/v1/history/external`.** Rejected on mechanics. That path is owned by
`/api/v1/history/{sensor_id}`, which resolves the segment against the configured
sensors; "external" would 404 as `sensor_not_found`. Declaring the literal route
first would work but leaves a landmine for anyone reordering routers. The feed is
also not a sensor — it has no IP, no calibration, no `logged` flag.

**An `include=wind` group on the outdoor history route,** joined by timestamp.
Rejected on principle and mechanics. It fuses EXTERNAL and D-READING provenance
into a single row, which ADR-0002 exists to prevent, and joining a sparse hourly
series onto 5-minute outdoor buckets makes `row_count` and `bucket_seconds` stop
meaning one thing.

**Value-comparison dedup** (skip when the numbers match the previous row).
Rejected: it invents an editorial policy. "Calm for three hours" is real data, and
the resulting gaps would be indistinguishable from feed outages.

**A separate `[external] log_history` flag.** Rejected for now. `enabled` already
means "this install uses the internet feed", and CLAUDE.md asks for restraint on
config options that no requirement demands. Adding the flag later is trivial and
backward-compatible.

**404 when the feed is disabled.** Rejected. Absence of internet is a normal state
for this project, not an error, and the dashboard's `fetchJson` cannot distinguish
a deliberate 404 from a broken URL. The `enabled` flag lets a client separate the
durable "no feed on this install" from the transient "feed on, nothing logged
yet" — the first hides a panel, the second shows a no-data affordance.

## Consequences

**On the locked "outdoor sensor only" decision.** That decision (2026-05-22) is
about the three ESP32 sensors: its stated consequence was reclassifying BUG-12 to
"the basement and indoor sensors are live-only *by design*". It predates the
external feed by a week — ADR-0001 had to invent the `EXTERNAL` provenance tag
precisely because internet data did not fit the existing taxonomy. Indoor and
basement remain live-only, and `outdoor_readings` remains local-sensor-only. This
ADR extends the *scope of logging* to a second, clearly-labelled category rather
than overturning that decision, and CLAUDE.md is amended to say so.

**No backfill is possible.** The regional charts are empty on the day this ships
and fill in going forward at the provider's update rate. A 7-day window will look
sparse for a week. This is unavoidable — the data was never recorded — and the
dashboard's NO DATA state exists to make it legible rather than look broken.

**Sample density is the provider's, not ours.** Expect ~1 row/hour, not the 12/hour
the refresh interval might suggest. At a 1-hour window with `bucket=auto` (which
resolves to raw), that can mean one or two points, which draws nothing with
`pointRadius: 0` — hence the "fewer than two points counts as no data" rule.

**Storage is negligible.** Roughly 8,760 rows/year deduped, well under 1 MB. No
retention policy, consistent with `outdoor_readings`, which has never had one.

**Rolling back the code is no longer sufficient.** A server built before this
change will refuse to start against a v2 database file, by design — the version
check hard-errors on a newer file rather than operating on a schema it does not
understand. A rollback must restore a pre-migration database file too. The
migration itself only adds a table and indexes: no `ALTER`, no data moved, and a
test builds a genuine v1 file with rows and asserts every row survives.

**Aggregation is per-column now.** Bucketing gained a policy map so the external
series can mean speeds, take the *peak* for gusts (a mean of gusts understates the
gust, which is the entire point of reporting one), and use a circular mean for
bearings. That last one also fixed a dormant wraparound bug on `course_deg`, which
was scalar-averaged: 350° and 10° averaged to 180°, due south instead of north.

## Revisit if

- A local anemometer is ever added. Wind would then become a D-READING quantity on
  `outdoor_readings`, and this table would hold only the regional comparison.
- Providers are switched mid-series. The stored `provider`/`source` columns make
  that detectable, but nothing currently warns a reader that a chart spans two
  sources.
- The table grows beyond a few MB, at which point a shared retention policy for
  both tables is worth more than one for either alone.
