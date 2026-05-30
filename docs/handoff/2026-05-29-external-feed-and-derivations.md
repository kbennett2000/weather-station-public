# Session Handoff — 2026-05-29
## Feature: Optional Internet External Feed, Extended Derivations, Dashboard Refresh

---

## Goal

Extend the weather server's `/api/v1/current` response with richer derived physics (wet-bulb,
VPD, density altitude, etc.), light/sky estimates, fused comfort/agronomy indices, and an
optional internet-sourced "external" block (wind + regional conditions from Open-Meteo, NWS,
or Wunderground). Expose a new `/api/v1/summary/{sensor_id}` endpoint for daily statistics
(hi/lo/avg, pressure tendency, degree days, DLI, Hargreaves ET0). Surface all new data in
the dashboard. Keep the server fully functional with zero internet access.

---

## Done

All work is committed and pushed to `origin/main`. Final HEAD is `64f5c81`.
Test suite: **267 tests, all green**. `mypy` and `ruff` clean.

### Backend — new modules

- `server/weather_server/external/` — three files:
  - `providers.py` — Open-Meteo (default, keyless), NWS, Wunderground adapters.
    Each returns a normalized `ExternalReading` dataclass. Wunderground `api_key` is
    scrubbed from logs (HIGH severity fix from code review).
  - `store.py` — thread-safe in-memory store for the last fetch result + timestamp.
  - `task.py` — background async task; polls the configured provider on a configurable
    interval (default 600 s); skips cleanly when `[external]` is disabled.
- `server/weather_server/derivations/fused.py` — wind chill, heat index, apparent
  temperature (Australian), THSW, Hargreaves ET0. All computed from local sensor data
  when no external feed is present; replace with internet values when present.
- `server/weather_server/derivations/light.py` — irradiance estimate, cloud cover
  fraction, UV index estimate, sky condition string. All flagged `estimated: true` in
  the API response.
- `server/weather_server/derivations/summary.py` — hi/lo/avg over a day window, pressure
  tendency (Pa/h), degree days (HDD/CDD base 65 F), DLI, Hargreaves ET0 aggregate.
- `server/weather_server/routes/external.py` — `GET /api/v1/external` standalone endpoint.
- `server/weather_server/routes/summary.py` — `GET /api/v1/summary/{sensor_id}` endpoint.
  Returns 404 for non-outdoor sensors (history is outdoor-only per design).
- Extended `server/weather_server/derivations/astronomy.py` — civil/nautical/astronomical
  twilight, golden hour / blue hour windows, current season, next solstice/equinox,
  solar azimuth/elevation, shadow length multiplier, next new moon / full moon dates.

### Backend — changes to existing modules

- `server/weather_server/main.py` — registers `external` background task on startup;
  mounts new routes; serves dashboard static files with `Cache-Control: no-cache` (was
  missing, caused stale `app.js` on deployed Pi).
- `server/weather_server/schemas.py` — new Pydantic models: `ExternalBlock`,
  `DerivedThermodynamicsBlock`, `DerivedSkyBlock`, `FusedIndicesBlock`,
  `SummaryResponse`; `CurrentResponse.external` is `Optional[ExternalBlock]` (absent
  when feed is disabled or last fetch failed).
- `server/weather_server/routes/history.py` — implemented `?from=` and `?to=` ISO-8601
  query params (were in the spec but wired to nothing before this session).
- `server/weather_server/config.py` — `[external]` TOML section parsed into
  `ExternalConfig`: `enabled`, `provider` (`open_meteo`|`nws`|`wunderground`),
  `api_key` (optional), `fetch_interval_seconds`.
- `server/weather.toml.example` — ships with `[external] enabled = true` and
  `provider = "open_meteo"` so the example demonstrates the feature without requiring
  a key. Lat/lon are `0.0` placeholders (intentional — a config-load test was relaxed
  to accept any in-range float).

### Dashboard

- `dashboard/app.js` — new REGIONAL panel (wind compass rose, fused indices, provenance
  caption line, NO-FEED offline state card reusing basement-offline visual language);
  Derived Thermodynamics panel; Today and Trends panel; adaptive feels-like label
  (switches between "apparent temp" and "heat index" depending on which is available,
  tagged with source); sky estimates; expanded astronomy (twilight windows, golden/blue
  hour, season, moon phase).
- `dashboard/index.html` — header quick-links for `/external` and `/summary` (raw JSON
  inspection; developer convenience, not user-facing navigation).
- `dashboard/style.css` — supporting styles for new panels, NO-FEED state, compass rose.

### Tests

New test files added this session:
- `server/tests/test_external_config.py`
- `server/tests/test_external_endpoint.py`
- `server/tests/test_external_providers.py`
- `server/tests/test_external_task.py`
- `server/tests/test_derivations_fused.py`
- `server/tests/test_derivations_light.py`
- `server/tests/test_derivations_summary.py`
- `server/tests/test_gaps.py` — fills coverage on edge cases flagged by code review

### Documentation

- `docs/adr/0001-optional-internet-external-data-feed.md` — ADR for the external feed.
  ADR-0002 (dashboard UX for the REGIONAL panel) was being drafted by a concurrent
  agent; verify it exists before referencing it.
- `docs/design/02-api-design.md` — synced to cover `external` block, `derived.sky`,
  fused indices, `summary` endpoint, `?from=`/`?to=` history params, `D-HISTORY` and
  `EXTERNAL` provenance tags.
- `docs/design/01-findings.md` — decisions log updated with new entries.
- `docs/02-install-and-configure.md`, `docs/03-using-the-dashboard.md` — updated.
- `README.md` — LAN-only claim reworded to "opt-in"; `[external]` section documented.
- `CLAUDE.md` — current-state block updated.

---

## Decisions

**Offline-first is a hard invariant.**
The acceptance test: with `[external]` disabled (or the provider unreachable), every
endpoint except `external` itself must return the same shape and values as when the
feed is live. The `external` block on `/api/v1/current` is `null` when offline; the
REGIONAL panel in the dashboard shows a NO-FEED card. Nothing else changes. This was
verified against a running instance (headless Chrome, network blocked). Do not add any
code path where a missing external result degrades derived thermodynamics, astronomy,
or summary.

**Provenance tags drive API placement.**
Two new tags were introduced: `EXTERNAL` (internet-sourced, flagged as such) and
`D-HISTORY` (derived from historical DB rows, not the current reading). Fields tagged
`EXTERNAL` live exclusively in the `external` block; fields tagged `D-HISTORY` live
exclusively in `summary`. No mixing of provenance in a single response block.

**Open-Meteo is the default provider; it requires no API key.**
NWS and Wunderground are opt-in overrides via `provider = "nws"` or
`provider = "wunderground"`. Wunderground requires `api_key`; NWS does not. The
`api_key` is never logged (fixed from code review — was leaking the raw value at DEBUG
level in a `requests` exception handler).

**REGIONAL panel is a first-class panel, not blended into the outdoor hero.**
The dashboard treats internet wind/conditions the same as a sensor: it's either
present or it isn't. When absent, it renders the same "offline" card that basement
uses. This makes the internet-optional nature obvious to the user and avoids confusing
blended provenance in the primary readings.

**`weather.toml.example` lat/lon are `0.0` placeholders.**
The user zeroed them deliberately. A config-load test that formerly required non-zero
coords was relaxed to accept any in-range float. If a future test needs realistic
derived values, use the real coords in the fixture or pass them explicitly — do not
tighten that config-load test back to non-zero.

**`Cache-Control: no-cache` on static dashboard files.**
Before this fix, the deployed Pi served a stale `app.js` after upgrades. FastAPI's
`StaticFiles` mount does not set this header by default. The fix is in `main.py` via a
custom `StaticFiles` subclass. After the next `git pull` + server restart on the Pi,
browsers will revalidate on every load and will not serve stale bundles again.

---

## In Progress

Nothing is half-finished in the working tree. The tree is clean.

ADR-0002 (dashboard UX — REGIONAL panel design decisions) was being drafted by a
concurrent agent during this session. Verify it landed at
`docs/adr/0002-dashboard-regional-panel.md` before the next session references it.

---

## Pending / Next Session

**Priority 1 — GTK tray widget.**
`widget/weather_tray.py` has not been updated to surface any of the new fields.
The natural additions are:
- Wind speed + direction (from `external.wind_speed_mph`, `external.wind_dir_deg`) if
  the feed is enabled; omit the line when `external` is null (existing omit-if-None
  pattern in the widget).
- Apparent temperature / feels-like (from `current.derived.fused.apparent_temp_c` or
  the local fallback in `derived.fused`).
- Optionally: a brief regional conditions string from `external.conditions`.

The widget currently polls `/api/v1/current` and maps fields manually. Adding lines
follows the same pattern as the existing `humidity`, `pressure`, and `dew_point` lines.
Target: keep the popup under ~20 lines; add the omit-if-None guard for external fields.

**Priority 2 — ADR-0002 verification.**
Confirm the concurrent agent wrote `docs/adr/0002-*.md`. If it's missing, draft it
from the decisions recorded in this handoff (REGIONAL panel rationale section above).

**Priority 3 — Cross-check confidence flag UX (optional).**
`derived.sky` fields are flagged `estimated: true`. The dashboard currently renders them
with a small "est." label. There is no confidence percentage or range displayed. If the
user wants tighter UX around uncertainty communication, this is the hook point.

**Priority 4 — Deploy to Pi.**
Steps needed on the live machine at `192.168.1.62`:
1. `git pull` in the repo directory.
2. Restart the `weather-server` systemd unit.
3. One hard-refresh in the browser (Ctrl+Shift+R). The `no-cache` fix means subsequent
   refreshes will be automatic going forward.
4. Confirm the REGIONAL panel loads (Open-Meteo is keyless; should work immediately).

---

## Open Questions

**For the user to decide:**
- Should the tray widget show internet wind even when the feed might be absent? The
  existing widget never shows "n/a" lines — it simply omits fields that aren't
  available. Confirm this is the desired behavior before implementing.
- `[BRANDING]` slots in the dashboard are still empty. These are human-owned
  placeholders; the code will not fill them.
- NWS requires a `user_agent` string in HTTP headers (their policy). Currently a
  generic user-agent is sent. If NWS is used in production, the user should supply an
  email-based user-agent string in config. Consider adding a `user_agent` key to
  `[external]`.

**Needs investigation:**
- The `httpx` / `starlette.testclient` deprecation warning (`StarletteDeprecationWarning:
  Using httpx with starlette.testclient is deprecated; install httpx2 instead`) appears
  in every test run. It does not affect correctness today but will become an error in a
  future Starlette release. Resolution: `pip install httpx2` and update the test client
  import if the package API differs.

---

## Watch Out For

**`weather.toml.example` lat/lon are `0.0` — this is intentional.**
The config-load test was relaxed to accept any in-range float. Do not interpret the
zero coordinates as a bug or tighten the test back. The real install's `weather.toml`
has real coords (`39.43326, -104.51888`).

**`external` block is `null`, not absent, when the feed is disabled.**
The JSON response includes `"external": null` rather than omitting the key. Dashboard
code uses `if (data.external)` guards, not `if ('external' in data)`. Keep this
consistent; a future change that removes the key rather than nulling it will silently
break the REGIONAL panel without a visible error.

**Provider `open_meteo` uses WMO weather codes for `conditions`.**
The adapter maps WMO integer codes to English strings. The mapping lives in
`external/providers.py`. If Open-Meteo changes their WMO code set (unlikely but
possible), `conditions` will return an unmapped integer string rather than failing —
this is intentional defensive behavior, but the string will look odd on the dashboard.

**History `?from=`/`?to=` params accept ISO-8601 strings, interpreted as UTC.**
There is no timezone conversion for query params. The dashboard currently passes
epoch-derived ISO strings which are always UTC. If a future client passes local-time
strings without a `Z` or offset, the window will be silently wrong. A validation note
exists in the history route docstring.

**The `no-cache` static-file fix is in `main.py`, not in Nginx/Apache.**
This project has no reverse proxy in front of FastAPI. If one is added later, the
proxy's own cache headers will take precedence and the `no-cache` setting in `main.py`
may be masked. Document this if a proxy is ever added.

**Fused `ET0` uses the Hargreaves method, not Penman-Monteith.**
Hargreaves requires only Tmax/Tmin/Tmean and solar radiation estimate. Penman-Monteith
would require wind speed and vapor pressure data that the local sensor always has, but
the station has no radiation sensor — so both methods use an estimated irradiance.
Hargreaves is documented as an approximation. Do not promote it to "precision ET" in
any user-facing text.
