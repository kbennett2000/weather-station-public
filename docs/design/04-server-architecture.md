# Weather Station Server — Process Architecture

Status: draft for review
Date: 2026-05-22
Scope: how the server's two concurrent workloads (outdoor logging, indoor/basement live polling) are organized into processes and tasks.

---

## Decision

**One process, one systemd unit, two internal async tasks.**

The FastAPI server hosts:

1. **Outdoor logger** — a background asyncio task that polls the outdoor ESP32 every 60 s and writes a row to SQLite. Runs from process startup to shutdown.
2. **HTTP handlers** — when a request hits `/api/v1/current`, the handler reads outdoor's latest row from SQLite and concurrently polls indoor and basement via `asyncio.gather`, with a short per-sensor timeout. A small in-memory TTL cache deduplicates concurrent polls.

No separate logger process. No separate liveness daemon. No shared cache across processes.

---

## The question

The system has three distinct workloads:

1. Persist outdoor readings to the database on a fixed cadence.
2. Surface live readings from indoor and basement sensors when the API is asked.
3. Serve API requests.

These can be partitioned across processes in several ways, and the polling for (2) can happen on different schedules. The question is which partitioning gives the cleanest operational model for a single-Pi deployment.

---

## Options considered

### Option A — Single process, on-demand polling for indoor/basement

One FastAPI process. Outdoor logging is a background asyncio task within it. Indoor and basement sensors are polled by the request handler when needed.

**Pros:**
- One process, one systemd unit, one log file, one thing to start/stop/debug.
- Coherent failure mode: if the API is down, nothing is running. No orphaned logger writing to a DB no one's reading.
- Concurrent polling via `asyncio.gather` means total request latency is bounded by the slowest single sensor poll, not the sum.
- TTL cache (5–10 s) deduplicates polls when multiple clients hit the API in quick succession.

**Cons:**
- Sensor-side latency leaks into API request latency. Worst case: indoor sensor is offline, request waits for the timeout (~3 s) before returning an `online: false` marker.
- A request that arrives during a sensor reboot will see "offline" until the next poll. Acceptable for a 30 s dashboard auto-refresh.

### Option B — Single process, background polling for everything

Same FastAPI process, but a second background task polls indoor and basement on a fixed cadence and caches the result. The request handler only reads from cache.

**Pros:**
- Predictable API latency. Sensor downtime never makes a request slow.
- Polling cadence is uniform and observable.

**Cons:**
- Another moving part. Two background tasks instead of one.
- Polls happen even when no client is looking, wasting a small amount of network traffic and ESP32 wakeups.
- Cache has a staleness window equal to the poll interval (e.g. 30 s). For a sensor that's actually being looked at right now, that's worse than on-demand polling.
- The complexity is only justified if API latency-under-failure is a meaningful concern, which on a LAN dashboard polling every 30 s, it isn't.

### Option C — Two processes (logger + API)

Outdoor logger runs as its own systemd unit (the current architecture, minus the indoor logger). The API process never writes to the DB; it only reads.

**Pros:**
- Clean separation of write and read responsibilities.
- Restarting the API doesn't interrupt logging.
- Each process is smaller and easier to reason about in isolation.

**Cons:**
- Two systemd units, two log files, two failure modes to monitor.
- Indoor and basement polling still has to live somewhere — either in the API process (on-demand, same as Option A) or in a third process (now we're up to three).
- The "clean separation" benefit is real in production systems with multiple API replicas, scaling concerns, or independent deployment cycles. None of those apply here.

### Option D — Logger writes everything, API only reads

All three sensors get logged. Indoor and basement go into their own tables. API reads everything from SQLite.

**Pros:**
- Maximally uniform. Every handler just reads the DB.
- Naturally trivial caching: the most recent row IS the cache.

**Cons:**
- Violates the previously-settled decision to log only outdoor.
- Adds storage for data we explicitly decided is uninteresting historically.
- The "uniformity" benefit doesn't outweigh the architectural backslide.

---

## Rationale for Option A

Three considerations tipped the decision:

**1. Async makes the latency concern mostly disappear.** The thing that would push toward Option B is "sensor polling shouldn't make API requests slow." With FastAPI and `asyncio.gather`, two parallel polls take as long as the slowest single one — say 100 ms in the healthy case, 3 s in the worst case (timeout on an offline sensor). For a dashboard that auto-refreshes every 30 s, a 3-second worst-case isn't a problem. Option B's latency advantage is real but small.

**2. Operational simplicity wins at this scale.** Every additional process is a systemd unit to configure, a log file to check, a startup-order dependency to think about, a failure mode to debug. For a hobby station on a Pi, the cost-benefit of "two processes for cleanliness" is upside down. One process is genuinely easier to live with, even if it's slightly less architecturally pure.

**3. Coherent failure semantics.** With one process, "the server is up" and "logging is happening" are the same state. With two processes, you can have the logger running but the API down (no one notices for a while), or the API up but the logger crashed (current readings work, history goes stale silently). Both of those failure modes are subtle, real, and easy to miss. One process makes the system's health a single yes/no question.

The TTL cache in Option A is the key design element that makes it competitive with Option B without the operational cost. A 5-second cache means:

- A dashboard refresh and a tray refresh within the same window only trigger one sensor poll.
- Adversarial-but-friendly clients (someone pounding F5) don't DOS the indoor sensor.
- Request latency for a cache hit is effectively zero.
- Real freshness is preserved — cache TTL is much shorter than any consumer's refresh cadence.

---

## Implementation sketch

The structure inside the FastAPI app:

```
weather_server/
├── main.py              # FastAPI app, lifespan event, route registration
├── config.py            # TOML loader, settings dataclass
├── db.py                # SQLite connection management, schema check, pragmas
├── logger_task.py       # Background outdoor poller
├── sensors.py           # Sensor poll abstraction (one function: poll_sensor(sensor_id))
├── derivations/
│   ├── readings.py      # Reading-bound derivations (dew point, °F, pressure conversions)
│   ├── location.py      # GPS-bound derivations (DMS, Maidenhead)
│   └── astronomy.py     # Time-of-request derivations (sun, moon)
├── routes/
│   ├── current.py       # /api/v1/current handlers
│   ├── history.py       # /api/v1/history/{sensor_id}
│   ├── sensors.py       # /api/v1/sensors
│   ├── astronomy.py     # /api/v1/astronomy
│   └── health.py        # /api/v1/health
├── schemas.py           # Pydantic response models from the API design doc
└── cache.py             # TTL cache (dict + asyncio.Lock, ~30 lines)
```

The lifespan event at startup:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.config = load_config("weather.toml")
    app.state.db = init_db(app.state.config.db_path)
    app.state.cache = TTLCache(default_ttl=5)
    app.state.logger_task = asyncio.create_task(
        outdoor_logger_loop(app.state.config, app.state.db)
    )
    yield
    # Shutdown
    app.state.logger_task.cancel()
    try:
        await app.state.logger_task
    except asyncio.CancelledError:
        pass
    app.state.db.close()
```

The outdoor logger loop:

```python
async def outdoor_logger_loop(config, db):
    outdoor = config.sensor_by_id("outdoor")
    interval = config.logger_interval_seconds  # default 60
    while True:
        try:
            data = await poll_sensor(outdoor, timeout=10)
            if data is not None:
                write_outdoor_row(db, data)
        except Exception:
            log.exception("outdoor logger iteration failed")
        await asyncio.sleep(interval)
```

The current-conditions handler:

```python
@router.get("/api/v1/current")
async def get_current(request: Request):
    config = request.app.state.config
    db = request.app.state.db
    cache = request.app.state.cache

    outdoor = read_latest_outdoor(db)

    indoor, basement = await asyncio.gather(
        cache.get_or_fetch("indoor", lambda: poll_sensor(config.sensor_by_id("indoor"), timeout=3)),
        cache.get_or_fetch("basement", lambda: poll_sensor(config.sensor_by_id("basement"), timeout=3)),
        return_exceptions=True,
    )

    astronomy = compute_astronomy(reference_location_from(outdoor, config))

    return build_current_response(outdoor, indoor, basement, astronomy)
```

The whole server is well under a thousand lines of Python.

---

## Trade-offs and escape hatches

The choice of Option A is reversible. If real-world experience reveals problems, here's what would push toward a different option:

| Symptom | Likely fix |
|---|---|
| API request p99 latency is dominated by indoor sensor timeouts | Move indoor/basement to background polling (Option B). The cache layer is already in place; just have it populated by a background task instead of on-demand fetches. |
| The outdoor logger gets blocked by a long-running API request | This would only happen if a request used blocking I/O. Stay async-clean and this can't happen. |
| Need to scale horizontally (multiple API replicas) | Extract the logger to its own process (Option C). At that point you're way outside hobby territory and this whole document is the wrong starting point. |
| Logger task silently dies and stops writing to DB | Add a healthcheck that flags `loggers.outdoor.ok = false` when `last_write_seconds_ago > 3 × interval`. Already in the API design as part of `/api/v1/health`. |

The escape hatches all preserve the API contract. Consumers don't notice which option is in use.

---

## What this means for the rest of the docs

Updates needed:

1. **`weather-station-api-design.md`** — the "Resolved design decisions" section can gain a "Process model" entry pointing to this doc.
2. **`weather-station-schema.md`** — the "How this connects to the rest of the system" section already says "the logger" in the abstract; that's now accurate to refer to the outdoor logger task inside the API process.
3. **`weather-station-findings.md`** — add a decisions-log entry for this choice.

No changes to the API surface, the schema, or any external contract.

---

## What's next

With the process model settled, the remaining implementation roadmap is:

1. **Server module layout details.** The directory tree above is a sketch; the actual interfaces between modules (e.g. what `poll_sensor` returns, what the cache API looks like) deserve a brief design pass before code.
2. **Dashboard rewrite scope.** What stays, what gets simpler, what (if anything) gets added. The dashboard becomes much thinner once it's just consuming `/api/v1/current` and `/api/v1/history/outdoor`.
3. **Tray rewrite scope.** Similar — the SunCalc port goes away, the calculation code goes away, the tray becomes a render-the-API-response widget.
4. **ESP32 sketch cleanup.** Drop the inline HTML status page (QUAL-05), the `/setOffset` endpoint (SEC-04), and remove the dead non-FreeRTOS sketches (QUAL-04). The sketches become genuinely small.
5. **Install script rewrite.** Address QUAL-02 and the cluster of install-script findings.
6. **README rewrite.** Reflects the new architecture, removes overclaims, documents the actual capabilities.

These can be tackled in any order. My instinct is #2 next (dashboard scope), because it's the largest remaining consumer-facing artifact and once it's settled, the rest is mechanical cleanup.
