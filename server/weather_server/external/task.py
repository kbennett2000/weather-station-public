"""Background task that refreshes the external observation on a timer.

Mirrors logger_task.outdoor_logger_loop: a cancellable loop that catches
every exception so a flaky network can never take the server down. It runs
OUTSIDE the request path, so a slow upstream never delays /api/v1/current.
When [external] is disabled the loop is never spawned.

Each successful fetch is also appended to the external_readings table so
the regional series has history (ADR-0003). The live /api/v1/current path
still reads the in-memory store; persistence is purely additive, and a DB
failure here is logged and swallowed rather than allowed to stop the feed.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime

from ..config import Config
from ..db import insert_external_reading, latest_outdoor_reading
from .providers import Observation, fetch_external
from .store import ExternalStore

log = logging.getLogger(__name__)


def resolve_reference_location(
    config: Config, db: sqlite3.Connection
) -> tuple[float, float] | None:
    """Reference coords for the external fetch: explicit override, then the
    outdoor sensor's latest GPS, then its configured fallback. None if no
    location is known (⇒ skip the fetch)."""
    ext = config.external
    if ext.lat_override is not None and ext.lon_override is not None:
        return ext.lat_override, ext.lon_override

    try:
        row = latest_outdoor_reading(db)
    except sqlite3.Error:
        row = None
    if row is not None:
        lat = row["latitude"]
        lon = row["longitude"]
        if lat is not None and lon is not None:
            return float(lat), float(lon)

    outdoor = config.outdoor
    if (
        outdoor is not None
        and outdoor.fallback_lat is not None
        and outdoor.fallback_lon is not None
    ):
        return outdoor.fallback_lat, outdoor.fallback_lon
    return None


async def external_fetch_loop(
    config: Config, db: sqlite3.Connection, store: ExternalStore
) -> None:
    ext = config.external
    if not ext.enabled:
        log.info("external feed disabled; fetch task exiting")
        return

    interval = ext.refresh_interval_seconds
    log.info("external feed enabled (provider=%s, every %ss)", ext.provider, interval)

    while True:
        try:
            ref = resolve_reference_location(config, db)
            if ref is None:
                log.info("external fetch skipped: no reference location yet")
            else:
                lat, lon = ref
                obs = await asyncio.to_thread(fetch_external, ext, lat, lon)
                if obs is not None:
                    now = datetime.now(UTC)
                    store.set(obs, now)
                    log.debug("external observation refreshed from %s", obs.source)
                    _persist(db, obs, now)
                else:
                    log.info("external fetch returned no data; keeping last-known")
        except asyncio.CancelledError:
            log.info("external fetch task cancelled")
            raise
        except Exception:
            log.exception("external fetch iteration failed")
        await asyncio.sleep(interval)


def _persist(db: sqlite3.Connection, obs: Observation, fetched_at: datetime) -> None:
    """Append the observation to external_readings, ignoring duplicates.

    The row is stamped with the provider's own `observed_at` when it gives
    one, so re-fetching the same observation collides with the UNIQUE
    (provider, timestamp) index and is dropped. Providers update far more
    slowly than the ~300s refresh interval — hourly, for both NWS stations
    and Open-Meteo model output — so without this the table would fill with
    a dozen identical rows per hour and the chart would imply a sample rate
    that does not exist.

    When a provider supplies no observation time we fall back to the fetch
    time, which always advances; `observed_at IS NULL` on the row records
    that the timing is ours, not theirs.
    """
    reference = obs.observed_at or fetched_at
    try:
        wrote = insert_external_reading(
            db,
            int(reference.timestamp()),
            {
                "observed_at": (
                    int(obs.observed_at.timestamp()) if obs.observed_at is not None else None
                ),
                "provider": obs.provider,
                "source": obs.source,
                "station_id": obs.station_id,
                "distance_km": obs.distance_km,
                "wind_speed_ms": obs.wind_speed_ms,
                "wind_gust_ms": obs.wind_gust_ms,
                "wind_direction_deg": obs.wind_direction_deg,
                "cloud_cover_pct": obs.cloud_cover_pct,
                "uv_index": obs.uv_index,
                "precip_mm": obs.precip_mm,
                "visibility_m": obs.visibility_m,
                "confidence": obs.confidence,
            },
        )
    except sqlite3.Error:
        # Never let a DB problem take the feed — or the server — down. The
        # live external block keeps working from the in-memory store.
        log.exception("failed to persist external observation")
        return
    log.debug("external observation %s", "logged" if wrote else "already logged")
