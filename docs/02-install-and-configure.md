# 02 · Installing the server

This is the server-side guide: pick a Linux box, run `install.sh`, edit two config files, browse to a dashboard. If [`01-building-the-sensors.md`](01-building-the-sensors.md) gave you one or more sensors serving JSON on the LAN, this doc turns them into something you actually look at.

When you're done, the dashboard at `http://<this-host>:8005` will be showing live data, the systemd service will be running at boot, and only port 8005 will be open in the firewall.

---

## Hardware

Pick one collector machine. It just has to be on the same LAN as the sensors. Options, with rough fit:

| Hardware | Verdict |
|---|---|
| **Raspberry Pi Zero 2 W** | Minimum. Works, but slow during pytest and any rebuilds. Recommended only for a "set and forget" install. |
| **Raspberry Pi 4 (2 GB+)** | The sweet spot for a small home-brew install. Plenty of CPU + RAM, USB-C power, runs cool. |
| **Any old laptop / mini-PC** | Fine. Ubuntu Server on a 10-year-old laptop you have in a drawer is great. |
| **A VM on an existing home server** | Fine. 1 vCPU + 512 MB RAM is plenty. |

**Disk / memory budget.** The whole footprint after install:

- Code + venv + Python deps: ~150 MB
- SQLite weather.db, 1 row/minute, raw rows + indexes: ~1 MB / month
- Dashboard static files: <1 MB

You can run this on a 4 GB SD card. The SQLite file grows monotonically; if you ever want to prune, see the note at the bottom.

**Network.** Pin the host's IP in your router (DHCP reservation) so the dashboard URL stays stable. No need for a static IP at the OS level — the installer doesn't configure the network at all.

---

## OS install

The installer is tested on **Ubuntu Server 22.04 / 24.04** and **Raspberry Pi OS Lite (Bookworm)**. Anything Debian-derived should work; CentOS / Fedora / Alpine will need port-by-port adaptation (apt vs dnf, no UFW out of the box, etc.).

If you're starting fresh:

- **Ubuntu Server:** [official install docs](https://ubuntu.com/tutorials/install-ubuntu-server). Pick the LTS, do a minimal install, enable SSH during setup.
- **Raspberry Pi:** [Pi Imager](https://www.raspberrypi.com/software/). Choose "Raspberry Pi OS Lite (64-bit)" — you don't need a desktop on the collector box. During Imager's "Edit Settings" step:
  - Set the hostname (e.g. `weatherbox`).
  - Enable SSH with username + password.
  - Set WiFi credentials.
  - Locale / keyboard.

Boot the device, SSH in, get to a prompt. The rest of this doc assumes you're on the collector machine.

---

## Run the installer

```bash
git clone https://github.com/kbennett2000/weather-station-public.git
cd weather-station-public
sudo ./install.sh                # server + dashboard only
# OR
sudo ./install.sh --with-widget  # also install GTK system libs for the tray widget
```

What [`install.sh`](../install.sh) does, in order:

1. **Validates `$SUDO_USER`.** The script must be invoked via `sudo` from a regular user account; it errors out (with a readable message) if you're logged in as `root` or somehow run it without sudo. Everything it installs ends up owned by `$SUDO_USER`.
2. **apt installs** `python3`, `python3-venv`, `python3-pip`, `sqlite3`, `ufw`, `curl`. With `--with-widget`, also `python3-gi`, `gir1.2-gtk-3.0`, `gir1.2-appindicator3-0.1`, `python3-requests`.
3. **Creates a Python venv** at `server/.venv` owned by your user.
4. **Editable-installs the server**: `pip install -e ./server`. The `weather-server` console-script entry point is now on the venv's PATH.
5. **Seeds `server/weather.toml`** from `server/weather.toml.example` (only if `weather.toml` doesn't already exist — re-running install.sh is safe).
6. **Seeds `branding.toml`** from `branding.toml.example` the same way.
7. **Writes a systemd unit** at `/etc/systemd/system/weather-server.service`. The unit runs `uvicorn weather_server.main:app --host 0.0.0.0 --port 8005` as `$SUDO_USER`, restarts on failure, logs to journald, and locks down filesystem writes to `server/` only.
8. **Enables UFW** with `allow ssh` + `allow 8005/tcp`. Nothing else is opened.

Optional flags:

- `--with-widget` — also installs the GTK system packages needed by the tray widget. Only matters on a Linux *desktop*; skip on a headless box.
- `--no-systemd` — install everything but don't write or enable the systemd unit. Useful for development where you'd rather `make dev` by hand.
- `--no-firewall` — leave UFW alone. Useful if you manage your firewall through some other tool.
- `--no-start` — don't auto-start the service after installing the unit. Useful when you want to edit `weather.toml` before the first launch.

Re-running `sudo ./install.sh` is safe and idempotent. It reconciles drift — re-installs apt packages, refreshes the venv, rewrites the systemd unit, re-applies the UFW rules. Existing `weather.toml` and `branding.toml` are never overwritten.

---

## Configure `server/weather.toml`

The installer copied [`weather.toml.example`](../server/weather.toml.example) to `weather.toml` if you didn't already have one. Open it and edit. The relevant sections:

### `[server]`

```toml
[server]
host = "0.0.0.0"
port = 8005
db_path = "weather.db"
dashboard_dir = "../dashboard"
branding_path = "../branding.toml"
```

- `host = "0.0.0.0"` — listen on every interface. Use `127.0.0.1` to restrict to the local machine only.
- `port = 8005` — the dashboard's public port. If you change it, also update the UFW rule (`sudo ufw allow <new-port>/tcp`) and any clients (widget config, OpenAPI URL).
- `db_path` — relative to the working directory the service runs from (which is `server/` under the systemd unit). The default `weather.db` puts the file at `server/weather.db`. Absolute paths work too.
- `dashboard_dir` / `branding_path` — usually leave the defaults. The systemd unit's `WorkingDirectory` is `server/`, so `../dashboard` and `../branding.toml` resolve to the repo root.

### `[logger]`

```toml
[logger]
interval_seconds = 60
http_timeout_seconds = 10
```

- `interval_seconds = 60` — how often the server polls the outdoor sensor and writes a row to SQLite. 60 s is a sensible default. Going below 30 s significantly increases disk writes; going above 300 s makes the dashboard's "history" look choppy.
- `http_timeout_seconds = 10` — give the sensor 10 s to respond before the logger marks the cycle as failed. Increase only if your sensors are unusually slow.

### `[cache]`

```toml
[cache]
ttl_seconds = 5
```

- Caches the indoor/basement responses for 5 seconds so multiple dashboard tabs don't hammer the sensors. Tune lower for snappier updates, higher to reduce upstream pressure.

### `[development]`

```toml
[development]
fixture_dir = "fixtures"
```

The example file ships with this section **enabled**, which makes the server read from `server/fixtures/*.json` instead of polling real sensors. Great for first-run testing — you can browse to the dashboard and see realistic data without any hardware connected.

**For production, comment out the whole `[development]` block.** That's the switch that flips the server from fixture mode to real HTTP polling. Restart the service afterwards.

### `[[sensors]]` blocks

One block per physical sensor. Example:

```toml
[[sensors]]
id = "outdoor"
role = "outdoor"
ip = "192.168.1.60"
has_gps = true
has_light = true
online_threshold_seconds = 120
temp_offset_c = -0.5
fallback_altitude_m = 1609.3
fallback_lat = 39.7392
fallback_lon = -104.9903
```

- `id` — short stable name. Appears as a key in `/api/v1/current.sensors`. Must be unique.
- `role` — `outdoor` or `indoor`. The server only logs history for the `outdoor` role.
- `ip` — the static IP you assigned when flashing the sketch. Find it in your router's DHCP table or use `arp -a` after the device boots.
- `has_gps` / `has_light` — feature flags. Set both true only on outdoor sensors.
- `online_threshold_seconds` — number of seconds without a successful poll before the sensor is marked `online: false`. 120 s (= 2 minutes) is a good default for sensors polled every 60 s.
- `temp_offset_c` — calibration. If your sensor consistently reads 0.5°C high vs. a trusted reference thermometer, set this to `-0.5`. Server-side; the ESP32 itself stores no offset.
- `fallback_altitude_m` (outdoor only) — used for sea-level pressure adjustment if GPS hasn't acquired a fix. Set to your installation's nominal elevation in metres.
- `fallback_lat` / `fallback_lon` (outdoor only) — used by the astronomy module if GPS has no fix. Set to your installation's coords (Google Maps right-click → "What's here").

**To add a new sensor** (say, a garage sensor):

1. Build and flash one more indoor-style sensor (per `01-building-the-sensors.md`).
2. Add a new `[[sensors]]` block with `id = "garage"`, `role = "indoor"`, and the device's IP.
3. Restart the service: `sudo systemctl restart weather-server`.
4. The dashboard's HTML currently has slots for outdoor / indoor / basement only. You'd also need to add a panel in `dashboard/index.html` and wire it in `dashboard/app.js`. That's a code change, not a config change.

---

## Configure `branding.toml`

The installer copies [`branding.toml.example`](../branding.toml.example) to `branding.toml`. This file feeds every `[BRANDING]` placeholder on the dashboard via the `/api/v1/branding` endpoint.

```toml
[header]
tagline = "Pick a one-liner that goes here when [taglines.rotating] is empty."

[footer]
text = "Whatever you want at the very bottom of the page."

[browser_title]
text = "Weather Station"  # appears in the browser tab

[states]
outdoor_offline = "Some friendly placeholder when outdoor is offline."
indoor_offline  = "…or indoor."
basement_offline = "…or basement."
loading = "Loading data…"

[error]
generic = "Something's wrong. Check the server logs."

[taglines]
rotating = [
    "First tagline",
    "Second tagline",
    "etc.",
]
```

Where each lands on the page:

| Field | Appears in |
|---|---|
| `header.tagline` / `taglines.rotating` | Top-right header strip. If `taglines.rotating` has any entries, one is picked at random per page load and shown there; otherwise `header.tagline` is used as a static string. |
| `footer.text` | The middle slot of the page footer. |
| `browser_title.text` | The browser tab title. |
| `states.outdoor_offline` etc. | A small grey line under each sensor panel's metrics. |
| `states.loading` | A banner between the header and the panels, visible only until the first `/api/v1/current` response. |
| `error.generic` | The same banner, in warm red, when the dashboard can't reach the API. |

Visual reference for the slot locations is in [`03-using-the-dashboard.md`](03-using-the-dashboard.md).

**Restart the service after editing branding.toml** — there's no hot reload.

---

## Start / restart the service

```bash
sudo systemctl restart weather-server.service
sudo systemctl status  weather-server.service        # one-shot check
journalctl -u weather-server.service -f              # tail logs
```

The service runs as your user (`$SUDO_USER`), in `WorkingDirectory=<repo>/server`, with writes locked to `server/` via systemd's `ProtectSystem=full` + `ReadWritePaths`. It restarts on failure (`Restart=on-failure`) and is enabled at boot (`systemctl enable` was done by the installer).

---

## Optional: install the widget

The tray widget is a separate Linux desktop process. It connects over HTTP to whatever server URL you tell it.

On a Linux desktop machine (not necessarily the collector box):

```bash
# If you didn't pass --with-widget to install.sh:
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-appindicator3-0.1 python3-requests

cp widget/config.toml.example widget/config.toml
$EDITOR widget/config.toml         # set server_url to point at the collector
```

Test:

```bash
python3 widget/weather_tray.py     # uses SYSTEM python; gi is an apt package
```

A thermometer icon should appear in your tray. Left-click → popup with full readout. To autostart on every login: on Ubuntu Desktop, open the **Startup Applications** tool, Add an entry with the command `/usr/bin/python3 /path/to/widget/weather_tray.py`.

---

## Verify

```bash
# Server reachable?
curl -s http://localhost:8005/api/v1/health | python3 -m json.tool

# Live data?
curl -s http://localhost:8005/api/v1/current | python3 -m json.tool

# Browser
xdg-open http://localhost:8005/        # or just hit it from another box
```

Expected within 30 seconds of `systemctl restart`:

- `/api/v1/health` returns `ok: true`, `db_reachable: true`, and a line per registered sensor.
- `/api/v1/current` returns a `sensors` map with one entry per registered sensor. Each shows `online: true` if reachable.
- The dashboard at `http://<host>:8005/` shows live numbers in every panel.

---

## Troubleshooting

**"I see the dashboard but every panel shows `--`."** The server can't reach the sensors. Three things to check:

1. `curl http://<sensor-ip>/data` from the collector box. If it fails, the issue is between the collector and the sensor — IP wrong in `weather.toml`, sensor unplugged, WiFi issue.
2. `journalctl -u weather-server.service -n 50`. The logger prints poll failures with the exact URL and error.
3. `cat server/weather.toml | grep -A1 "\[development\]"`. If `fixture_dir` is set, you're still in fixture mode — comment out the `[development]` block and restart.

**"I see no dashboard at all" (connection refused).** The service isn't running. Run `systemctl status weather-server.service` and `journalctl -u weather-server.service -n 100`. Typical failures:

- `weather.toml` has a syntax error (missing quote, bad indentation). Validate with `python3 -c "import tomllib; tomllib.load(open('server/weather.toml', 'rb'))"`.
- Port 8005 is already in use by something else: `sudo lsof -i :8005`.

**"Pressure looks wrong."** Three possibilities:

1. `temp_offset_c` set incorrectly on the outdoor sensor. Temperature affects nothing about pressure — but if temperature is off, you'll notice and assume pressure is too.
2. Wrong `fallback_altitude_m`. Sea-level pressure is computed from `altitude_m` + the barometric formula. If GPS has no fix yet, the server uses `fallback_altitude_m`. Compare against your actual elevation at [maps.google.com](https://maps.google.com).
3. Drift in the BME280 itself. Compare against a local weather station; if you're off by a fixed amount, you can adjust `fallback_altitude_m` to compensate (each 8 m of altitude error ≈ 1 hPa).

**"Sensor shows offline."** `online: false` means the server saw the sensor at some point but hasn't successfully polled it in `online_threshold_seconds`. Causes:

- Sensor lost WiFi. Power-cycle the sensor, check serial monitor.
- Sensor IP changed (DHCP collision). Put the sensor's IP in your router's DHCP reservation table.
- Sensor's BME280 is failing reads. `curl <sensor-ip>/data` — if it returns `{"error":"..."}`, replace the BME280 module.

**"Time is wrong."** Check `astronomy.timezone` in `/api/v1/current`. If it's `UTC` instead of your IANA zone (like `America/Denver`), the outdoor sensor has no GPS fix and the `fallback_lat`/`fallback_lon` resolution failed. Set those explicitly in `weather.toml` if they're not already.

**"Disk is filling up over time."** SQLite is appending one row per minute to `outdoor_readings`. After a year: ~525,000 rows, maybe 50 MB. After ten years: half a gig. If that's a problem on your hardware, you can manually trim:

```bash
sqlite3 server/weather.db "DELETE FROM outdoor_readings WHERE timestamp < strftime('%s', 'now', '-1 year');"
sqlite3 server/weather.db "VACUUM;"
```

There's no built-in pruning; SQLite is configured in WAL mode so the deletes are safe even while the server is running.

---

## Next

You have live data flowing. Time to learn the dashboard:

→ [`03-using-the-dashboard.md`](03-using-the-dashboard.md)
