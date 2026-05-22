# Weather Station — Dashboard and Widget Scope

Status: draft for review
Date: 2026-05-22
Scope: what the new dashboard and tray widget contain, how they look, what they no longer do.

---

## Decisions feeding into this design

Already settled:

- All forecasting tabs and code are deleted (no `weatherAnalysis.js`, no `predictConditions`, no "Forecast & Analysis" or "My Forecast" tabs).
- Both clients consume the new `/api/v1/...` endpoints exclusively. No direct sensor polling, no in-client SunCalc, no in-client dew-point math.
- Both clients become thin: the dashboard is a React/HTML render layer over the API; the tray is a GTK render layer over the API.

New decisions in this doc:

- Dashboard moves from port 80 to a configurable port, **default 8005**. The iptables 80→8000 redirect in the install script goes away. Port 80 is freed for a future menu/landing service on the same host.
- The dashboard's visual style is reworked from the current generic-card layout to an **instrument-panel aesthetic** (rationale and details below).
- All fields currently displayed by the tray widget are added to the dashboard.
- The tray widget's visual presentation and information set are preserved as-is. Only the data plumbing changes.

---

## Dashboard

### What stays

- The title **"Jones Big Ass Weather Dashboard"** and subtitle **"Collectin' Some Good Ass Weather Data!"** — both prominent. The title is the project's name, not negotiable.
- The current set of charts (temperature, humidity, pressure, dewpoint, visible light, IR light).
- The time-window selector (1h / 6h / 12h / 24h / 7d).
- The split into Outdoor / Indoor / Basement live sections.
- The GPS-status indicator (the red/yellow/green dot with the tooltip).
- Date and Last-Updated metadata.
- The general fact of running in a browser, on the LAN, with no auth and no cloud.

### What's removed

- The entire navigation: no more tabs. "Current Conditions" is the only view. The `dashboard-nav` block at the top of the current `dashboard.html` goes away.
- `weatherAnalysis.js` and all references to it.
- The "My Forecast" Babel block and its `SharedComponents`.
- The duplicate script tags, the unused `tensorflow.min.js`, the in-browser Babel transpilation. (BUG-02, BUG-03, BUG-04, PERF-01, PERF-02, PERF-03.)
- The SunCalc, dew-point, absolute-humidity, sea-level-adjustment functions in dashboard JavaScript. (These move to the server.)
- The `/?url=...` proxy pattern in `getData()`. The dashboard calls `/api/v1/current` and `/api/v1/history/outdoor` and that's it.
- The `hardcoded elevation = 1972` magic number. (Part of BUG-21's resolution.)
- The undeclared `hadError` variable. (BUG-01.)
- The commented-out dead code blocks. (QUAL-07.)

### What's added — fields from the widget

These are currently in the tray but not on the dashboard. All come from `/api/v1/current` and `/api/v1/astronomy` in the new API:

| Field | Source in API response | Notes |
|---|---|---|
| Day length | `astronomy.sun.day_length_seconds` | Display as `H.H hrs` |
| Time to/since sunset | `astronomy.sun.seconds_to_sunset` | Sign indicates "to" vs "since" |
| Time to sunrise | `astronomy.sun.seconds_to_sunrise` | Only meaningful after sunset |
| Sun position (azimuth + altitude) | `astronomy.sun.azimuth_deg`, `altitude_deg` | Format: `Az 156° Alt 42.3°` |
| Moon position (azimuth + altitude + distance) | `astronomy.moon.{azimuth_deg, altitude_deg, distance_km}` | Same pattern |
| Moon illumination % | `astronomy.moon.illumination_pct` | Already partially present; make explicit |
| Light in lux (raw value) | `sensors.outdoor.raw.lux` | Currently dashboard only shows visible/IR as percentage |
| GPS in decimal degrees (visible, not just tooltip) | `sensors.outdoor.location.{lat, lon}` | Move from tooltip to a visible row |
| GPS in DMS | `sensors.outdoor.location.dms` | New |
| Maidenhead grid square | `sensors.outdoor.location.maidenhead` | New |
| Satellite count (visible, not just tooltip) | `sensors.outdoor.location.satellites` | Move from tooltip |
| Timezone | `astronomy.timezone` + `astronomy.local_time` | Server's resolved zone |

This roughly doubles the volume of information on the page, which is one of the reasons the layout has to be reworked.

### What's added — new visualizations

Two additions that fall naturally out of having sun/moon position data:

- **Sky-position polar plot.** A small SVG panel showing the sun and moon on a polar coordinate system (azimuth around the rim, altitude as distance from center). Sun gets a yellow dot, moon gets a phase-appropriate icon. Updates with the data. This is the kind of "looks like real equipment" element that earns its space.
- **Day arc.** A horizontal track showing dawn → sunrise → solar noon → sunset → dusk with a marker at "now." Tells the at-a-glance story of where in the day you are.

These come at no data cost (the API already provides everything needed) and meaningfully improve the dashboard's character.

### Port change

Currently the dashboard is reachable on port 80 via an iptables `PREROUTING` redirect from 80 to 8000 (the proxy actually binds 8000). This was simplicity by way of complexity — three moving parts to spell "open browser, type the IP."

New behavior:

- The server binds directly to a configurable port. Default: **8005**.
- The TOML config carries `[server] port = 8005`.
- The iptables redirect in the install script is removed.
- The UFW firewall rule for port 80 in the install script is removed.

This resolves **MIN-03** (the iptables indirection) and reduces the scope of **SEC-07** (only one port is opened in the firewall now). Port 80 is left available for the future menu/landing page service.

The dashboard URL becomes `http://<host>:8005`. The README needs to reflect this; **MIN-05** (the README that says "point your browser at the collector machine" without a port) is closed by being specific.

### Visual direction — "instrument panel"

The current dashboard is functional but indistinct: white cards on a light grey background, default fonts, default Chart.js styling. It looks like a generic web app circa 2020. For a hobbyist project with a name like "Jones Big Ass Weather Dashboard," the look should match the personality.

The proposed direction is **instrument panel**: dark background, big bold readouts, subtle accent glow on status indicators, monospace or technical-feeling typography for numeric values, sans-serif for labels. Think aircraft cockpit or marine nav station, not minimalist Bauhaus.

Specific stylistic anchors:

- **Background:** very dark blue-grey (something like `#0f1419` or `#11161c`), not pure black. Softens contrast.
- **Cards/panels:** slightly lighter than the background, with thin borders and subtle inner shadows. No drop shadows (those feel like the current cardy look).
- **Primary readouts:** large, weight 600+, in a slightly amber/warm-white color (`#f5d76e`-ish) that suggests warm instrument lighting. Numbers should look *important*.
- **Labels:** uppercase, letter-spaced, smaller, muted grey.
- **Charts:** dark theme, single accent color per chart, thin lines, minimal grid. Chart.js supports dark themes well; the styling is config rather than custom code.
- **Status indicators:** the existing GPS-status LED concept is good — extend it. Sensor online status, freshness, satellite count, etc. all get small glowing dots in green/amber/red.
- **Sky polar plot:** dark circular panel with subtle radial grid, sun and moon rendered as glowing dots.
- **Title treatment:** the project name in a slightly oversized display font at the top, subtitle in italic below in muted grey. Prominent but not garish.
- **Personality slots:** specific places in the layout that are intentionally left for project branding — see the next section.

Alternatives considered (recorded for completeness):

| Alternative | Why not |
|---|---|
| Modern minimalist (white background, restrained, calm) | Loses personality. Doesn't match the project's voice. |
| Retro-futurist / skeuomorphic | Costs a lot more design work for diminishing returns. Could be a v2 if the instrument-panel direction lands and someone wants more flourish. |
| Light mode primary | The dashboard tends to be left open on a screen running 24/7. Dark is friendlier to that use. A light variant can be added later via CSS variables. |

The instrument-panel direction is reversible. If real screens land badly, switching out a color palette and typography scale via CSS variables is a one-afternoon job.

### Personality / branding slots

These are explicit places in the layout where Jones-flavored references, jokes, and Easter eggs belong. Marked as **`[BRANDING]`** in implementation so they're easy to spot.

| Slot | Description |
|---|---|
| **Title block** | The "Jones Big Ass Weather Dashboard" + subtitle is the obvious one. Could optionally have a small logo/icon. |
| **Header tagline strip** | A small italic strip below the subtitle, can rotate through a small set of Jones-isms on each page load. |
| **Empty/loading states** | When a sensor is offline or data is loading, the placeholder text is a branding slot rather than just "No data." |
| **Footer** | Small text at the bottom of the page. Project credits / "built with..." / Jones reference. |
| **Page title (`<title>`)** | Browser tab title can be funnier than the current one. |
| **Error states** | When `/api/v1/health` reports a problem, the user-facing message is a branding slot. |

The content of each slot is intentionally **not** specified in this document. The user supplies the actual text/references; the layout reserves the space.

### Out of scope

- Mobile-specific design beyond "doesn't break on a phone." The dashboard is primarily a screen-on-a-wall or browser-tab dashboard.
- Authentication. Still none.
- Real-time push (WebSocket/SSE). Continued polling on a 30 s interval is fine.
- Configurable themes. Dark is the only theme in v1.
- Per-user preferences (chart range memory across reloads, etc.). Maybe v2.

---

## Widget (tray)

### What stays

- The GTK + AppIndicator3 structure.
- The system-tray icon showing current temperature.
- The left-click → popup menu pattern.
- The exact information shown in the popup. Per the project owner: "the current UI is perfect."
- The 30-second refresh cadence.
- "Open dashboard" menu item.

### What changes

The widget's data plumbing is replaced. Nothing visual changes.

| Old | New |
|---|---|
| Polls `http://192.168.1.60/data` directly | Polls `http://<server>:<port>/api/v1/current` |
| Embedded SunCalc Python port (~200 lines) | Reads `astronomy` block from API response |
| Local dew-point calculation | Reads `derived.dewpoint_c/f` from API |
| Local absolute humidity calculation | Reads `derived.absolute_humidity_g_m3` |
| Local DMS conversion | Reads `location.dms` |
| Local Maidenhead calculation | Reads `location.maidenhead` |
| Local timezone lookup (`timezonefinder`) | Reads `astronomy.timezone` |
| Local pressure-inHg conversion (BUG-21 root cause) | Reads `derived.pressure_sealevel_inhg` |
| Dashboard URL hardcoded as `http://192.168.1.62` | Single configurable `server_url` (read from a small config file or env var) |

### Code shrinkage

The widget's `weather_tray.py` should drop from 961 lines to **roughly 300**. The deletions are:

- The entire `SunCalc` class (~200 lines).
- `calculate_dew_point`, `calculate_absolute_humidity`.
- `decimal_to_dms`, `maidenhead`.
- The `astral` and `timezonefinder` imports and their consumers.
- The line-by-line comment explanations (QUAL-01). The new widget should be commented at section level, not line level.

What's left is essentially: GTK setup, fetch from API on a timer, build the popup label string, handle clicks.

### Widget configuration

A small TOML or config file alongside the widget script:

```toml
server_url = "http://192.168.1.62:8005"
refresh_seconds = 30
```

That's the entire config surface. The server URL handles both data fetching and the "Open dashboard" menu item (no more divergent `192.168.1.60` data IP vs `192.168.1.62` dashboard IP — MIN-01).

### Dependency reductions

Packages no longer needed by the widget:

- `astral` (sun calculations) — server's job
- `timezonefinder` (timezone lookup) — server's job
- `pytz` (timezone math) — server returns ISO strings already in the correct zone
- The 80 MB of timezone data shipped with `timezonefinder`

What's left: `gi` (GTK), `requests`. The widget becomes installable with two pip packages plus a system-level GTK install.

### Out of scope

- Multiple-server support (one widget instance reads from one server).
- Configurable display fields. The user said the UI is perfect; we don't add toggles for what was already approved.
- Light-theme tray icon variant. AppIndicator handles dark/light icon switching at the OS level.

---

## How this maps to findings

| Finding | Status after this work |
|---|---|
| BUG-01 (`hadError` undeclared) | Closed — dashboard rewritten |
| BUG-02 (duplicate script tags) | Closed |
| BUG-03 (unused TensorFlow.js) | Closed |
| BUG-04 (dev React build) | Closed — switch to production builds or eliminate React entirely (deferred to implementation; see below) |
| BUG-21 (pressure inHg mismatch) | Closed — both clients read the same API field |
| MIN-01 (widget opens wrong IP) | Closed — single configurable URL |
| MIN-03 (iptables port-80 redirect) | Closed — direct bind to 8005 |
| MIN-05 (README dashboard URL ambiguity) | Closed — README will state the port |
| PERF-01 / PERF-02 / PERF-03 (page load weight) | Closed — clean rebuild |
| QUAL-01 (over-commented widget) | Closed — widget rewrite reduces lines and recomments at section level |
| QUAL-06 (inconsistent JS style) | Closed |
| QUAL-07 (commented-out dead code) | Closed |
| SEC-07 (firewall opens port 80) | Reduced — only 8005 opened |
| ARCH-05 (live vs historical separation) | Closed — both flow through one API |

---

## Deferred to implementation

1. **React vs vanilla JS.** The current dashboard uses React via in-browser Babel transpilation, which is unnecessary weight for what's mostly DOM updates and Chart.js. Worth deciding whether to keep React (with proper production build, no Babel) or drop it entirely in favor of vanilla JS or a lightweight framework (Alpine.js, Preact). My lean: **vanilla JS with Chart.js**, given the new dashboard's logic is small. But this is an implementation question, not a scope question.
2. **Visual mockup.** This document specifies direction, not pixels. A small HTML mockup of the new dashboard layout is the natural next artifact, once the scope here is approved.
3. **Widget config file format.** TOML matches the server's choice and reads with stdlib `tomllib`. Default location: `~/.config/weather-tray/config.toml`. Worth confirming before writing it.
4. **Where Jones-branding content actually lives.** This document reserves the slots; the user fills them in either in code or in a separate "branding.toml" that the dashboard reads.

---

## What's next

After this scope is approved, the natural sequence is:

1. **Visual mockup** of the new dashboard (HTML/CSS artifact, no backend).
2. **Server module interface design** (the deferred-from-architecture item — what `poll_sensor` returns, how the cache works, how derivations are organized).
3. **Implementation pass** on the server.
4. **Implementation pass** on the dashboard against the live API.
5. **Implementation pass** on the widget.
6. **ESP32 sketch cleanup** (drop the inline HTML, drop `/setOffset`, drop legacy sketches).
7. **Install script rewrite.**
8. **README rewrite.**

Steps 3–8 can largely be done in parallel once the server stabilizes.
