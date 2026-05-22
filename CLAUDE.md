# CLAUDE.md

This file orients Claude Code to the project. **Read it before doing anything.**

## What this project is

Jones Big Ass Weather Dashboard — a DIY networked weather station. ESP32 sensors (outdoor with GPS, indoor, basement) feed data to a Linux box running on the home LAN. That box runs an API server, logs outdoor history to SQLite, and serves a web dashboard plus a Linux system-tray widget.

The repo originally shipped a working but rough first version. A design pass has been completed and the resulting documents live in `docs/design/`. **This rebuild is greenfield against those design docs.** The existing source files in the repo (`weatherProxy.py`, `weatherLogger_*.py`, `dashboard.html`, `weatherAnalysis.js`, the various sketches, `installScriptUbuntu.sh`, `js/`) are reference material for understanding "what's there now" — they are **not** being refactored. The new implementation starts fresh from the design.

## Read these first, in order

Before writing or running any code:

1. `docs/design/README.md` — Map of the design docs (start here)
2. `docs/design/01-findings.md` — Original code review + **Decisions log** (the single most important section in the whole project)
3. `docs/design/02-api-design.md` — HTTP API contract
4. `docs/design/03-schema.md` — SQLite schema
5. `docs/design/04-server-architecture.md` — Process model
6. `docs/design/05-clients-scope.md` — Dashboard and widget scope
7. `docs/design/06-dashboard-mockup.html` — Visual target for the dashboard (open in a browser to view)

The decisions log in `01-findings.md` records *why* every major design choice was made. When in doubt, that's the place to look first.

## Locked decisions — do not re-litigate

The following are settled. If you believe one is wrong, **surface it as a question before changing direction**. Do not silently override:

- **Forecasting is removed.** No prediction, no analysis tabs, no `weatherAnalysis.js`.
- **Storage:** SQLite (WAL mode), single file, greenfield. No MySQL/MariaDB.
- **Logged data:** outdoor sensor only. Indoor and basement are live-only (current readings via API poll, no history retained).
- **Server framework:** FastAPI.
- **Config format:** TOML, parsed with stdlib `tomllib`.
- **Derived values:** computed server-side at read time. DB stores raw readings only.
- **Pressure handling:** stored as `pressure_pa` (raw station pressure in Pa). API exposes four distinct fields — `pressure_station_hpa`, `pressure_station_inhg`, `pressure_sealevel_hpa`, `pressure_sealevel_inhg` — to prevent the ambiguity bug documented in the findings (BUG-21).
- **Timezone:** resolved dynamically via `timezonefinder` from outdoor GPS coordinates. No internet required.
- **Dashboard port:** default 8005, configurable. No iptables redirect from port 80.
- **Process model:** single FastAPI process. Two internal async tasks: outdoor logger loop + on-demand polling of indoor/basement with a 5s TTL cache.
- **Visual aesthetic:** instrument-panel. Saira Stencil One for title, JetBrains Mono for readouts, IBM Plex Sans Condensed for labels. Warm amber on near-black. The mockup at `06-dashboard-mockup.html` is the **visual contract** — match it.
- **Branding slots:** every place marked `[BRANDING]` in the mockup is a *placeholder* for the human to fill in with project-specific references. **Do not invent content for these slots.** Leave them visibly empty until the human supplies the text.

## Technology stack

- **Python 3.11+** (required for stdlib `tomllib`)
- **FastAPI + uvicorn** for the server
- **SQLite** via stdlib `sqlite3`
- **`requests`** for sensor polling
- **`timezonefinder`** for IANA timezone lookup (ships offline)
- **Vanilla JavaScript + Chart.js** for the dashboard. **No React. No Babel. No Tailwind.** The current dashboard uses all three; the rebuild drops them.
- **GTK3 + AppIndicator3** for the widget (Python `gi` bindings)
- **Target host:** Raspberry Pi Zero 2 W or any Ubuntu Server box

## Target project structure

```
weather-station-public/
├── CLAUDE.md                    # This file
├── README.md                    # User-facing project README (rewritten in phase 6)
├── docs/
│   ├── design/                  # Read-only design inputs
│   │   ├── README.md
│   │   ├── 01-findings.md
│   │   ├── 02-api-design.md
│   │   ├── 03-schema.md
│   │   ├── 04-server-architecture.md
│   │   ├── 05-clients-scope.md
│   │   └── 06-dashboard-mockup.html
│   ├── rpiSetup.md              # Existing user docs (to be reviewed in phase 6)
│   └── ubuntuServerSetup.md
├── server/
│   ├── weather_server/          # FastAPI app
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── cache.py
│   │   ├── logger_task.py
│   │   ├── sensors.py
│   │   ├── schemas.py
│   │   ├── derivations/
│   │   │   ├── readings.py
│   │   │   ├── location.py
│   │   │   └── astronomy.py
│   │   └── routes/
│   │       ├── current.py
│   │       ├── history.py
│   │       ├── sensors.py
│   │       ├── astronomy.py
│   │       └── health.py
│   ├── tests/
│   ├── pyproject.toml
│   └── weather.toml.example
├── dashboard/                   # Static files served by the API
│   ├── index.html
│   ├── style.css
│   └── app.js
├── widget/
│   ├── weather_tray.py
│   └── config.toml.example
├── sketches/                    # ESP32 firmware (cleanup only, not rebuild)
│   ├── outdoor.ino
│   └── indoor.ino
└── install.sh
```

Legacy files removed at the end of the rebuild: `weatherProxy.py`, `weatherLogger_Indoor.py`, `weatherLogger_Outdoor.py`, `dashboard.html`, `weatherAnalysis.js`, `js/`, `installScriptUbuntu.sh`, the non-FreeRTOS sketches.

## Phased delivery

Work is split into six phases. **Do not start a new phase until the previous one is reviewed and accepted by the human.** Each phase has a clear "done" test.

### Phase 1 — Server with mock data

Build the FastAPI server: SQLite schema, derivation functions, all six endpoints from `02-api-design.md`, Pydantic models for every response, OpenAPI docs at `/docs`. **No real sensor polling yet.** Use a fixture file with sample outdoor/indoor/basement readings so the server can be tested without hardware. The logger task is implemented but reads from the fixture instead of an ESP32.

**Done when:**
- `curl http://localhost:8005/api/v1/current` returns valid JSON matching `02-api-design.md`.
- Every endpoint returns the right shape for both success and the documented error cases (404 for unknown sensor, 404 for non-outdoor sensor history, etc.).
- The four pressure fields are present and computed correctly (verify with a Denver-elevation test case: station ~804 hPa / 23.75 inHg, sea-level ~1023 hPa / 30.21 inHg).
- OpenAPI docs render at `/docs`.
- Tests cover at least: each derivation function, each endpoint's response shape, the pressure-quadruple, the offline-sensor case.

### Phase 2 — Real sensor integration

Replace the fixture with real HTTP polling. The logger task starts writing real rows to SQLite at the configured interval. Indoor/basement sensors get polled on demand with the TTL cache. Reading-bound derivations apply real calibration offsets from `weather.toml`.

**Done when:** the server runs on the actual Pi, logs real outdoor data to SQLite, and `/api/v1/current` reflects current sensor readings within a few seconds of reality.

### Phase 3 — Dashboard rewrite

Vanilla JS + Chart.js, served as static files by FastAPI. The implementation matches `06-dashboard-mockup.html` — that mockup is the visual contract. All data comes from `/api/v1/current` and `/api/v1/history/outdoor`. Time-window selector wired up (1h/6h/12h/24h/7d). Polar sky plot and day arc render with real data.

**Done when:** the dashboard loaded in a browser matches the mockup visually, shows live data, and the time-window selector changes the charts.

### Phase 4 — Widget rewrite

Python GTK tray widget reads from the API instead of polling the sensor directly. All embedded SunCalc / dew-point / Maidenhead / `timezonefinder` code is **deleted**. Information shown in the popup matches the existing widget (the human likes the UI as-is and explicitly said not to change it).

**Done when:** the widget runs on a Linux desktop, shows current temperature in the tray, and the click popup shows the same fields as the existing widget — but `weather_tray.py` is ~300 lines instead of ~960.

### Phase 5 — ESP32 sketch cleanup

Drop the inline HTML status page from each sketch (`handleRoot()`). Drop the `/setOffset` endpoint. Remove the dead non-FreeRTOS sketches (`jonesBigAssWeatherStation_indoor.ino`, `jonesBigAssWeatherStation_outdoor.ino`). Keep only the FreeRTOS versions, renamed to `outdoor.ino` and `indoor.ino`. WiFi credentials and IP stay as hardcoded constants — config provisioning is out of scope.

**Done when:** the sketches compile, the sensors still report data on `/data`, and the deleted endpoints/files are gone from the repo.

### Phase 6 — Install script and README

Rewrite `installScriptUbuntu.sh` as `install.sh`. Install the new stack (FastAPI, uvicorn, GTK deps for the widget). Drop the iptables redirect. Open only port 8005 in UFW. **Do not hardcode a username** — derive from `$SUDO_USER` or prompt. Rewrite the top-level `README.md` to reflect the new architecture: accurate port, no forecasting claims, accurate description of basement support (live-only, no history).

**Done when:** a fresh Ubuntu Server VM can be brought up by running the install script and lands on a working dashboard at `http://<host>:8005`.

## Behavioral guidance

- **Don't invent jokes or branding.** `[BRANDING]` slots in the mockup are placeholders. Leave them visible until the human fills them in.
- **Don't refactor the existing code.** The rebuild is greenfield. Old files are reference material only.
- **Don't add features not in the design docs.** If something seems obviously missing, ask before adding.
- **Don't edit the design docs.** They're read-only inputs. If you discover a real spec defect, raise it as a question and let the human update them.
- **Write tests as you go.** Pytest is fine. Aim for "the schema in `02-api-design.md` is enforced by tests," not 100% coverage.
- **Commit often, with clear messages.** Each commit should be reviewable on its own.
- **Code identifiers stay professional.** The README, code comments, and UI text can have personality (this is a hobby project, not enterprise software), but variable names, function names, and module names should be straightforward.
- **Match the visual mockup precisely.** Typography, color, spacing, the polar plot, the equipment-code labels in panel corners. If something in the mockup feels off and you'd like to change it, ask first.

## Current state

- Design phase: **complete**.
- Implementation phase: **not yet started**.
- Existing legacy code in the repo has not been touched yet.

This section gets updated as phases complete.
