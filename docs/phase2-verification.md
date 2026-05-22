# Phase 2 — Real-sensor verification

Phase 2 is "done" when the server, pointed at the real ESP32 sensors on
the LAN, logs outdoor data to SQLite and `/api/v1/current` reflects
current conditions within one logger interval.

The pytest suite includes an end-to-end integration test
(`tests/test_integration_real_polling.py`) that exercises the same flow
against a localhost fake-ESP32 HTTP server, so the *code path* is
verified automatically. This document covers the additional checks the
human runs against actual hardware before signing off the phase.

## Pre-flight

1. ESP32 sensors are powered on and reachable on the LAN.
2. `curl http://<sensor-ip>/data` returns JSON (or `{"error":"..."}` —
   the adapter handles both).
3. The host running the weather server is on the same LAN.

## Setup

```bash
cd server
cp weather.toml.example weather.toml
$EDITOR weather.toml
```

In `weather.toml`:
- **Disable fixture mode.** Comment out (or delete) the entire
  `[development]` block.
- **Set real IPs** in each `[[sensors]]` entry's `ip = "..."` field.
- **Outdoor `fallback_lat` / `fallback_lon`** can stay at the example
  Denver values or be set to your installation's nominal coordinates;
  they're only used if GPS hasn't acquired a fix yet.
- **`temp_offset_c`** per-sensor: this is where calibration lives now.
  The ESP32 no longer stores its own offset (BUG-06).

Start the server:

```bash
.venv/bin/uvicorn weather_server.main:app --host 0.0.0.0 --port 8005
```

## Verification checklist

### 1. Logger is writing real rows

After ~`logger.interval_seconds` (60 by default):

```bash
sqlite3 weather.db "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM outdoor_readings;"
```

Row count should be > 0, MAX(timestamp) close to `date +%s`.

### 2. `/api/v1/current` reflects current upstream readings

```bash
curl -s http://localhost:8005/api/v1/current | jq '.sensors.outdoor.raw.temperature_c, .sensors.outdoor.age_seconds'
```

Temperature should match what `/data` returns directly from the outdoor
ESP32. `age_seconds` should be < the logger interval.

### 3. Indoor / basement use on-demand polling

```bash
curl -s http://localhost:8005/api/v1/current/indoor | jq '.sensor.raw.temperature_c, .sensor.online'
```

Should return current indoor reading with `online: true`. Indoor and
basement data does **not** appear in SQLite — they are live-only.

### 4. The "I walked outside" test

This is the canonical Phase 2 done check: change the actual upstream
reading and confirm it propagates to `/current` within one logger
interval.

1. Note `/current/outdoor` temperature.
2. Move the outdoor sensor to a meaningfully different temperature
   (e.g. bring it inside, or breathe on it for 30 s — the BME280 is
   sensitive).
3. Wait one `logger.interval_seconds`.
4. Hit `/current/outdoor` again. Temperature should reflect the change.

### 5. Offline behavior

1. Unplug or block one sensor (e.g. block its IP in your router).
2. Wait `online_threshold_seconds`.
3. Hit `/api/v1/current`. The offline sensor should show `online: false`
   with stale `age_seconds`, and the rest of the response should still
   come back OK.
4. Hit `/api/v1/health`. For an offline outdoor sensor, the logger
   entry's `ok` will flip false once `last_write_seconds_ago > 3 *
   interval_seconds`.

### 6. BUG-08 (`nan` token in wire JSON) handling

If a sensor channel partially fails (e.g. TSL2591 errors but BME280 OK),
the sketch may emit `"lux": nan` in the JSON. The adapter sanitizes
these to `null` and the rest of the reading is preserved. Confirm with:

```bash
curl -s http://<sensor-ip>/data
```

If you see `nan` tokens, then check that `/api/v1/current` still
returns the non-nan fields populated (e.g. temperature/humidity present
when light fields are null).

## Troubleshooting

- **Empty `/current/outdoor.raw`** — the wire-format adapter parsed an
  empty payload. Check `/data` directly with curl and confirm the
  ESP32 is returning what the sketches in `sketches/` are expected to
  emit.
- **`/current/<id>` returns 503 `sensor_no_data`** — the sensor has
  never reported. Check connectivity and IP in `weather.toml`.
- **`/health.ok == false` while sensors look online** — DB unreachable
  or outdoor logger hasn't written in 3× the interval. Check the
  `weather.db` permissions and the server logs.

## What changes vs. Phase 1

Nothing on the API surface. Phase 2 is purely the swap from
`FixtureSensorSource` to `HttpSensorSource` (the factory picks based on
whether `[development] fixture_dir` is set). All consumers — dashboard,
widget, anything that talks to `/api/v1/*` — are unaffected.
