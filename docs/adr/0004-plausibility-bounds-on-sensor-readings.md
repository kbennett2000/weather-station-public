# 0004. Plausibility bounds on sensor readings, enforced on ingest and on read

Date: 2026-09-29
Status: Accepted

## Context

The sea-level pressure chart showed a spike of 1.58×10¹²⁹ inHg. The suspect was
the ageing BME280, but the logged data cleared it: across all 176,706 outdoor
rows (May 22 – Sep 29), raw station pressure never left 792–815 hPa.

The spike came from the GPS instead. The outdoor sketch reads position through
TinyGPS, which reports "invalid" sentinels until the receiver gets its first fix
after a cold boot: lat/lon 1000, altitude 999999999 cm (so 10,000,000 m), speed
and course ~1e7, and 255 satellites. The sketch passed them through, the logger
stored them, and sea-level pressure (`station × exp(g·alt / R·T)`) turned a
10,000 km altitude into ~1e129 hPa. When a sentinel row sat alone in a bucket,
`math.exp` overflowed and the endpoint returned 500. Every reboot logged a few
of these rows: 32 between Aug 6 and Sep 29.

Commit 9a1ac38 dropped out-of-range GPS fields at ingestion. That left two gaps:

1. Only GPS fields were checked. A failing sensor could still log an impossible
   temperature, humidity, pressure or light value.
2. Rows already stored stayed poisoned. History and the 7D/30D summary kept
   spiking or failing with 500 until each row aged out of the window.

A locked decision also constrains the fix: **the DB stores raw readings only;
derived values are computed at read time.**

## Decision

One table, `weather_server/plausibility.py::PLAUSIBLE_RANGES`, gives inclusive
physical bounds for every weather and GPS field. A value outside its range is a
fault, not weather, and is **treated as missing: that field only**. The rest of
the reading stands, so a glitching lux channel doesn't cost a good temperature.

The table is enforced at both boundaries:

- **Ingestion.** `wire_format` calls `drop_implausible()` on every outdoor and
  indoor payload before it is logged or served live. For outdoor readings this
  happens before `full_spectrum` is derived, so a refused `ir` can't leak into
  the sum.
- **Read-back.** `db.latest_outdoor_reading` and `db.outdoor_readings_in_range`
  (the only two outdoor reads) select ranged columns as
  `CASE WHEN c BETWEEN lo AND hi THEN c END`. Stored bad values read as NULL.

The bounds are deliberately loose. They separate sensor faults from weather,
not unusual weather from normal weather. Temperature allows −50…60 °C, which
admits the 46 °C readings from sun on the housing: those are real readings of
a real (if badly shaded) sensor.

## Alternatives considered

- **Ingestion only, plus a one-off SQL cleanup.** This means editing stored
  rows, which the raw-storage rule argues against. It also has to be redone
  whenever a bound is added or tightened.
- **Refuse the whole reading.** Stricter, but a single bad channel would
  throw away every good one alongside it.
- **Spike / rate-of-change filtering.** This would catch in-range glitches, but
  the data shows none, and it needs per-field tuning and neighbour context.
  Not justified yet.
- **Guard the derivations (catch the overflow).** This hides one symptom but
  still serves a garbage position and a garbage pressure.

## Consequences

- Stored sentinel rows are neutralised the moment the server is deployed, with
  no migration. The raw values stay on disk.
- A missing altitude falls back to the sensor's `fallback_altitude_m`, so that
  setting must match the station's real altitude. If it doesn't, rows without
  a GPS altitude show a sea-level pressure step: about 45 hPa at the Pi's
  original Denver default of 1609 m versus the station's ~1970 m.
- Refused ingestion values are logged at INFO (`refused out-of-range
  readings: …`). Read-side filtering is silent.
- Adding a field or changing a bound is one line in `PLAUSIBLE_RANGES`, and it
  applies retroactively.
- The external feed (`external_readings`) isn't covered. Its values come from
  a forecast provider, not from our hardware.

## Revisit if

- In-range glitches start appearing (a sensor that drifts or sticks rather
  than failing outright). That is the point to consider rate-of-change checks.
- The station moves somewhere the bounds don't fit (above 9,000 m, say).
