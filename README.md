# Jones Big Ass Weather Dashboard

A DIY networked weather station: ESP32 sensors → a Linux box on the LAN → a browser dashboard and a Linux system-tray widget.

<!-- Add a screenshot of the dashboard here, e.g.:
![Dashboard](docs/images/dashboard.png)
-->

## What is this?

One or more ESP32 boards (each with a BME280 plus, for outdoor, a TSL2591 light sensor and a NEO-6M GPS) sit on your home network reporting weather data over plain HTTP. A small FastAPI server on a Linux box polls them, writes outdoor readings to SQLite, and serves both an instrument-panel-style web dashboard and a JSON API. A separate Linux tray widget reads the same API for an always-visible temperature readout.

Three sensor roles are supported out of the box: **outdoor** (full sensor suite, GPS-tagged, history logged), **indoor** (BME280 only, live-only), and **basement** (BME280 only, live-only). The outdoor sensor's history is preserved in SQLite; indoor and basement are intentionally not logged.

Nothing leaves your LAN. No cloud, no auth (it's a LAN device), no forecasting models.

## Architecture

```
┌────────────────────┐
│  ESP32 outdoor     │  BME280 + TSL2591 + NEO-6M + OLED  (192.168.1.60)
│    FreeRTOS        │  HTTP GET /data → JSON
└─────────┬──────────┘
          │
          │ (logger task polls every 60s, writes to SQLite)
          │
          ▼
┌────────────────────┐       ┌────────────────────┐       ┌────────────────────┐
│  Indoor / Basement │──────▶│   FastAPI server   │──────▶│   SQLite           │
│   (BME280 only)    │  HTTP │   weather_server   │ INSERT│   outdoor only,    │
│   (on-demand poll) │       │   port 8005        │       │   WAL mode         │
└────────────────────┘       └─────────┬──────────┘       └────────────────────┘
                                       │
                                       │ HTTP /api/v1/* (JSON) + /dashboard/* (static)
                                       │
                ┌──────────────────────┼──────────────────────┐
                ▼                      ▼                      ▼
       ┌────────────────┐    ┌────────────────┐    ┌────────────────┐
       │ Web dashboard  │    │ Linux tray     │    │ Anything else  │
       │ (vanilla JS +  │    │ widget         │    │ that speaks    │
       │  Chart.js)     │    │ (GTK +         │    │ HTTP JSON      │
       │                │    │  AppIndicator) │    │                │
       └────────────────┘    └────────────────┘    └────────────────┘
```

Single FastAPI process. Outdoor sensor on a polling loop (1-minute default); indoor/basement on demand with a 5-second TTL cache so multiple dashboard tabs don't hammer them.

## What's in this repo

| Path | What it is |
|---|---|
| [`server/`](server/) | FastAPI server, SQLite logger, derivation modules, pytest suite. The `weather-server` package lives under `server/weather_server/`. |
| [`dashboard/`](dashboard/) | Vanilla JS + Chart.js dashboard, served as static files by the API at `/dashboard/`. No React, no Babel, no Tailwind. |
| [`widget/`](widget/) | Linux GTK3 system-tray widget. Reads `/api/v1/current` every 30 seconds; popup shows the same fields as the legacy widget. |
| [`sketches/`](sketches/) | ESP32 firmware (FreeRTOS). One sketch per physical sensor: `outdoor.ino`, `indoor.ino`, `basement.ino`. |
| [`docs/design/`](docs/design/) | The design documents that drove the rebuild. Start with [`docs/design/README.md`](docs/design/README.md); the decisions log in [`docs/design/01-findings.md`](docs/design/01-findings.md) is the canonical "why" reference. |
| [`docs/phase2-verification.md`](docs/phase2-verification.md), [`docs/phase5-verification.md`](docs/phase5-verification.md) | On-hardware checklists used when bringing up real sensors and reflashing firmware. |
| [`Makefile`](Makefile) | Common developer commands: `make dev`, `make test`, `make widget`, `make install`. Run `make help`. |
| [`install.sh`](install.sh) | One-shot installer for a fresh Ubuntu/Debian host (apt deps + venv + systemd unit + UFW rule). |

## Quick start — server + dashboard on a fresh host

Bring up a fresh Ubuntu Server (or any Debian-derived) box, then:

```bash
git clone https://github.com/kbennett2000/weather-station-public.git
cd weather-station-public
sudo ./install.sh                 # add --with-widget if you want the tray
```

The installer:

- Installs `python3`, `python3-venv`, `sqlite3`, `ufw`, `curl` via apt.
- Creates a venv at `server/.venv` owned by your user (derived from `$SUDO_USER`).
- `pip install -e ./server` so the FastAPI app is on the path.
- Drops a systemd unit at `/etc/systemd/system/weather-server.service` that runs `uvicorn` on port 8005, restarts on failure, and logs to journald.
- Opens TCP 8005 in UFW. **Nothing else.** No iptables, no port 80 redirect, no static IP rewrite.

After it finishes:

```bash
$EDITOR server/weather.toml                       # set your sensor IPs
sudo systemctl restart weather-server.service
journalctl -u weather-server.service -f           # tail logs
```

Then open `http://<this-host>:8005` in any browser on the LAN.

## Quick start — tray widget on your Linux desktop

The widget is a separate, optional process. It runs on any Linux desktop that can reach the server's URL — same box or any other LAN box.

```bash
sudo ./install.sh --with-widget
$EDITOR widget/config.toml                        # set server_url
make widget                                       # or: python3 widget/weather_tray.py
```

Add `python3 /path/to/widget/weather_tray.py` to your desktop's autostart if you want it on every login. The widget uses the **system** Python (not the server's venv) because PyGObject (`gi`) ships as an apt package, not pip.

## Configuration

### Server — `server/weather.toml`

Copy [`server/weather.toml.example`](server/weather.toml.example) (the installer does this for you) and edit. Important keys:

- `[server] port` — defaults to `8005`. Match this in the systemd unit and widget config if you change it.
- `[[sensors]]` blocks — one per physical device. Each carries `id`, `role`, `ip`, calibration offsets, and online thresholds.
- `[development] fixture_dir` — if set, the logger reads from fixture JSON files instead of polling real sensors. Useful for offline development; **comment out for production**.

### Widget — `widget/config.toml`

Two keys: `server_url` (e.g. `http://192.168.1.62:8005`) and `refresh_seconds` (default `30`).

### Sketches

WiFi credentials and the device's static IP are hardcoded constants near the top of each `.ino`. Edit before flashing. There's no over-the-air config; this is by design — the sketches stay simple and never expose a config endpoint to the LAN.

## Developer workflow

```bash
make install         # one-time: create venv, pip install -e ./server[dev]
make dev             # uvicorn --reload on port 8005
make test            # pytest (currently 112 tests, runs in ~6s)
make check           # lint + typecheck + test
make widget          # run the tray with system python
```

OpenAPI docs render at `http://localhost:8005/docs` when the server is up.

## Hardware

- Raspberry Pi Zero 2 W, or any Linux machine (Ubuntu Server LTS recommended for the production box)
- ESP32 dev boards — one per physical sensor location
- BME280 (temperature / humidity / pressure) on every sensor
- TSL2591 (light) on the outdoor sensor only
- NEO-6M GPS on the outdoor sensor only
- 0.96" SSD1306 OLED (optional, every sensor)

### Pin connections (per ESP32)

I²C devices (BME280, TSL2591, OLED) share the bus on GPIO21 (SDA) / GPIO22 (SCL). The GPS is on Serial2.

**BME280:** VIN → 3V3, GND → GND, SCL → GPIO22, SDA → GPIO21, CSB unconnected, SDO → GND.

**TSL2591 (outdoor only):** VIN → 3V3, GND → GND, SCL/SDA shared with BME280, INT unconnected.

**NEO-6M GPS (outdoor only):** VCC → 3V3, GND → GND, TX → GPIO16 (RX2), RX → GPIO17 (TX2).

**OLED (optional):** VCC → 3V3, GND → GND, SCL/SDA shared with BME280.

## License

[MIT](LICENSE). Use it, fork it, hack it — keep the copyright notice in copies.
