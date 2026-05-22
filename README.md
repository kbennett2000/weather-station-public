# Jones Big Ass Weather Dashboard

A DIY networked weather station: ESP32 sensors → a Linux box on the LAN → a browser dashboard and a Linux system-tray widget. Nothing leaves your LAN. No cloud, no auth, no forecasting models.

![Dashboard](docs/images/01-dashboard-full.png)

## Documentation

If you're new here, read these three in order. They're written to be standalone — you should be able to go from zero to working station by following them.

1. **[Building the sensors](docs/01-building-the-sensors.md)** — parts list, wiring diagrams, flashing the ESP32 sketches, mounting suggestions.
2. **[Installing the server](docs/02-install-and-configure.md)** — `install.sh` walkthrough, configuring `weather.toml` and `branding.toml`, systemd, troubleshooting.
3. **[Using the dashboard](docs/03-using-the-dashboard.md)** — annotated tour of every panel, the API, building your own consumer.

## What's in this repo

| Path | What it is |
|---|---|
| [`server/`](server/) | FastAPI server, SQLite logger, derivation modules, pytest suite. |
| [`dashboard/`](dashboard/) | Vanilla JS + Chart.js dashboard, served as static files by the API at `/dashboard/`. |
| [`widget/`](widget/) | Linux GTK3 system-tray widget. Reads `/api/v1/current`; popup shows the same fields as the dashboard. |
| [`sketches/`](sketches/) | ESP32 firmware (FreeRTOS). One sketch per physical sensor: `outdoor.ino`, `indoor.ino`, `basement.ino`. |
| [`install.sh`](install.sh) | One-shot installer for a fresh Ubuntu/Debian host (apt deps + venv + systemd unit + UFW rule). |
| [`Makefile`](Makefile) | Developer commands: `make dev`, `make test`, `make widget`, `make help`. |
| [`docs/`](docs/) | The three end-user docs above, plus design history under [`docs/design/`](docs/design/) and on-hardware verification checklists. |

## Minimum quick start

```bash
git clone https://github.com/kbennett2000/weather-station-public.git
cd weather-station-public
sudo ./install.sh
$EDITOR server/weather.toml          # set your sensor IPs, drop fixture mode
$EDITOR branding.toml                # optional: fill in the [BRANDING] slots
sudo systemctl restart weather-server.service
```

Then open `http://<this-host>:8005/`. If anything's unclear, [`02-install-and-configure.md`](docs/02-install-and-configure.md) has the full walkthrough.

## Developer workflow

```bash
make install     # one-time: create venv, pip install -e ./server[dev]
make dev         # uvicorn --reload on port 8005
make test        # pytest (118 tests, ~6s)
make check       # lint + typecheck + test
make help        # everything else
```

OpenAPI docs at `http://localhost:8005/docs` when the server is running.

## How we got here

This codebase was rebuilt from scratch in 2026 against a set of design documents that live in [`docs/design/`](docs/design/). The original code was a working but rough first version; the rebuild kept the project's identity while replacing the architecture (MySQL → SQLite, React + Babel → vanilla JS, three Python services → one FastAPI app, iptables port-80 redirect → direct bind to 8005, embedded SunCalc in the widget → server-side derivation).

The canonical "why was this designed this way" reference is the decisions log in [`docs/design/01-findings.md`](docs/design/01-findings.md). Every locked-in design choice — SQLite over MySQL, no forecasting, vanilla JS over a framework, the dashboard's instrument-panel aesthetic, dropping the `/setOffset` endpoint — has its reasoning recorded there. If you're considering a substantive change and want to know whether it was already considered, that's the place to look first.

## License

[MIT](LICENSE). Use it, fork it, hack it — keep the copyright notice in copies.
