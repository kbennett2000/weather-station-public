# Phase 5 — ESP32 sketch cleanup verification

Phase 5 is "done" when the new sketches compile and flash cleanly, the
existing `/data` endpoint still returns valid JSON, the deleted
endpoints are gone, and BUG-08 (the `nan` token in the wire JSON) is
fixed at the source.

This document is the on-hardware checklist the human walks through
after the code-side cleanup lands. Nothing here can be automated from
the laptop — every check requires a real ESP32 on the LAN.

## What changed in this phase

- `sketches/outdoor.ino` (was `jonesBigAssWeatherStation_FreeRTOS_outdoor.ino`)
- `sketches/indoor.ino` (was `jonesBigAssWeatherStation_FreeRTOS_indoor_main.ino`,
  IP `192.168.1.61`)
- `sketches/basement.ino` (was `jonesBigAssWeatherStation_FreeRTOS_indoor_jr.ino`,
  IP `192.168.1.63`)
- Deleted: the two non-FreeRTOS sketches (`jonesBigAssWeatherStation_indoor.ino`,
  `jonesBigAssWeatherStation_outdoor.ino`)

Per-sketch edits:

- Inline HTML status page in `handleRoot()` is gone. The endpoint now
  returns a one-line `text/plain` identifier so curl pokes still get a
  readable response.
- `/setOffset` endpoint + `handleSetOffset` function removed from the
  outdoor sketch. The `TEMP_OFFSET` constant remains as a hardcoded
  calibration value; runtime mutation is no longer exposed (SEC-04).
- `handleData()` now routes every float through a `floatJson()` helper
  that emits `null` for NaN instead of letting `String(NaN)` print the
  invalid literal `"nan"` (BUG-08).
- WiFi credentials, IP addresses, and the FreeRTOS task structure are
  unchanged. This was cleanup, not refactoring.

The wire-format adapter (`server/weather_server/wire_format.py`) keeps
its `nan`→`null` regex sanitizer as defense-in-depth — useful when an
old un-reflashed sketch is still on the LAN. The comment in
`floatJson()` points there.

## Pre-flight

1. Arduino CLI (or the IDE) installed with the ESP32 board package and
   the libraries the existing sketches already depend on (BME280,
   TSL2591, TinyGPS++, AsyncTCP / ESPAsyncWebServer, FreeRTOS).
2. The server is running and pointed at the real sensors
   (Phase 2 setup; see `docs/phase2-verification.md`).
3. A backup of the current flashed firmware on each device is not
   strictly required, but you may want to note the current `/data`
   response from each sensor first as a baseline.

## Verification checklist

### 1. Sketches compile

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 sketches/outdoor.ino
arduino-cli compile --fqbn esp32:esp32:esp32 sketches/indoor.ino
arduino-cli compile --fqbn esp32:esp32:esp32 sketches/basement.ino
```

Each should finish without errors. Warnings about unused includes are
OK; this is hobbyist code and the includes are intentional.

If you use the Arduino IDE instead of CLI: open each sketch, Verify
(Ctrl-R / Cmd-R). Same outcome.

### 2. Sketches flash and the device boots

Pick one sketch at a time. Connect the ESP32 over USB. Flash:

```bash
arduino-cli upload --fqbn esp32:esp32:esp32 --port /dev/ttyUSB0 sketches/outdoor.ino
```

Open the serial monitor at 115200 baud. The boot log should mention:

- WiFi connecting + IP address
- FreeRTOS tasks created (`SensorTask`, `WebServerTask`,
  `GPSTask` for outdoor only, `DisplayTask`, `WiFiWatchdog`)
- `HTTP server started`

If the device boots into a panic / continuous reset loop, the most
likely cause is a watchdog timeout from a sensor read — not a Phase 5
change. Roll back firmware and investigate separately.

### 3. `/data` still returns valid JSON

```bash
curl -s http://<sensor-ip>/data | jq .
```

Expected: a JSON object with the same field names as before
(`temperatureC`, `temperatureF`, `humidity`, `pressure`, etc.). `jq`
parsing it without complaint is the key signal. If `jq` errors, BUG-08
might be in play — see check 5.

### 4. `/` returns plain text, not HTML

```bash
curl -s -i http://<sensor-ip>/
```

Expected:

- `200 OK`
- `Content-Type: text/plain`
- Body: a short identifier like
  `Jones Big Ass Outdoor Sensor — see /data for JSON`

If you see HTML, the device is still running the old firmware. Reflash.

### 5. `/setOffset` returns 404 on the outdoor sensor

```bash
curl -s -i 'http://<outdoor-ip>/setOffset?value=0.0'
```

Expected: `404 Not Found`. The handler and the route registration are
both gone. If you get `200 OK`, the device is still running old
firmware. Reflash.

### 6. BUG-08 — invalid-JSON regression check

This one is hardware-dependent. The bug only surfaces when a sensor
channel returns NaN — most commonly when the TSL2591 (outdoor light
sensor) read fails or when the BME280 has a brief I²C glitch.

**Easiest reproduction:** physically cover the TSL2591 with opaque
tape for 30+ seconds. If the sensor library returns NaN for `lux`,
hit `/data`:

```bash
curl -s http://<outdoor-ip>/data | jq .lux
```

- **Pre-fix behavior:** `lux: nan` in the raw response, `jq` errors
  with `parse error: Invalid numeric literal`.
- **Post-fix behavior:** `lux: null`, `jq` prints `null`, rest of the
  reading is intact.

If you can't reliably trigger NaN from the sensors, an alternate
proof: confirm the helper compiles in by grepping the sketch:

```bash
grep -c 'floatJson' sketches/outdoor.ino     # expect: 13
grep -c 'floatJson' sketches/indoor.ino      # expect: 6
grep -c 'floatJson' sketches/basement.ino    # expect: 6
```

### 7. Server still ingests cleanly

After all three sensors are reflashed:

```bash
curl -s http://localhost:8005/api/v1/current | jq '.sensors | keys'
```

Expected: `["basement", "indoor", "outdoor"]`, each block populated.

Watch the server log for ~5 minutes. There should be no warnings about
`wire_format`, no `JSONDecodeError`, and no entries like "field X is
nan, coercing to null" (that path still exists in `wire_format.py` but
should now run zero times against the new firmware).

### 8. WiFi reconnect behavior unchanged

This isn't a Phase 5 change, but it's worth confirming we didn't
accidentally break it. Power-cycle your home AP (or the sensor) and
watch the serial log. The existing watchdog task should detect the
drop, attempt reconnects, and resume responding to `/data` once WiFi
comes back. If reconnect behavior degraded, that's a regression — flag
it before signing off the phase.

## Done criteria

Sign off Phase 5 when:

- [ ] All three sketches compile (check 1)
- [ ] All three sensors flash and boot (check 2)
- [ ] `/data` returns valid JSON on all three (check 3)
- [ ] `/` returns text/plain identifier on all three (check 4)
- [ ] `/setOffset` returns 404 on the outdoor sensor (check 5)
- [ ] BUG-08 is closed — either confirmed via covered TSL2591 (check 6)
  or accepted as code-confirmed via grep
- [ ] Server sees all three sensors at `online: true` (check 7)
- [ ] WiFi reconnect behavior is unchanged (check 8)

Phase 6 (install script + README rewrite) starts after sign-off.
