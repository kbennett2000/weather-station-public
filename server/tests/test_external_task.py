"""External fetch task: disabled no-op, failure tolerance, ref-location."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from weather_server.config import load_config_from_dict
from weather_server.db import init_db, insert_outdoor_reading
from weather_server.external.providers import Observation
from weather_server.external.store import ExternalStore
from weather_server.external.task import external_fetch_loop, resolve_reference_location

_BASE = {
    "server": {"db_path": ":memory:"},
    "sensors": [
        {
            "id": "outdoor",
            "role": "outdoor",
            "ip": "10.0.0.1",
            "has_gps": True,
            "fallback_lat": 39.4,
            "fallback_lon": -104.5,
        }
    ],
}


def _config(external: dict | None = None) -> object:
    raw = dict(_BASE)
    if external is not None:
        raw = {**_BASE, "external": external}
    return load_config_from_dict(raw)


def test_resolve_ref_location_prefers_override(tmp_path) -> None:
    db = init_db(tmp_path / "w.db")
    cfg = _config({"enabled": True, "lat_override": 1.0, "lon_override": 2.0})
    assert resolve_reference_location(cfg, db) == (1.0, 2.0)


def test_resolve_ref_location_uses_latest_gps(tmp_path) -> None:
    db = init_db(tmp_path / "w.db")
    insert_outdoor_reading(db, timestamp=1000, payload={"latitude": 12.0, "longitude": 34.0})
    cfg = _config({"enabled": True})
    assert resolve_reference_location(cfg, db) == (12.0, 34.0)


def test_resolve_ref_location_falls_back_to_config(tmp_path) -> None:
    db = init_db(tmp_path / "w.db")
    cfg = _config({"enabled": True})
    assert resolve_reference_location(cfg, db) == (39.4, -104.5)


async def test_loop_disabled_exits_immediately(tmp_path) -> None:
    db = init_db(tmp_path / "w.db")
    cfg = _config(None)  # external absent ⇒ disabled
    store = ExternalStore()
    # Should return promptly without ever fetching.
    await asyncio.wait_for(external_fetch_loop(cfg, db, store), timeout=1.0)
    assert store.get() is None


async def test_loop_survives_fetch_failure(tmp_path, monkeypatch) -> None:
    db = init_db(tmp_path / "w.db")
    cfg = _config({"enabled": True, "refresh_interval_seconds": 600})
    store = ExternalStore()

    calls = {"n": 0}

    def boom(*args, **kwargs):
        calls["n"] += 1
        raise ConnectionError("offline")

    monkeypatch.setattr("weather_server.external.task.fetch_external", boom)

    task = asyncio.create_task(external_fetch_loop(cfg, db, store))
    # Give the loop a moment to run its first (failing) iteration.
    for _ in range(50):
        await asyncio.sleep(0.01)
        if calls["n"] >= 1:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls["n"] >= 1  # it tried
    assert store.get() is None  # failure left the store empty, no crash


async def test_loop_keeps_empty_when_fetch_returns_none(tmp_path, monkeypatch) -> None:
    db = init_db(tmp_path / "w.db")
    cfg = _config({"enabled": True, "refresh_interval_seconds": 600})
    store = ExternalStore()

    calls = {"n": 0}

    def none_fetch(*args, **kwargs):
        calls["n"] += 1
        return None  # provider up, but no data (e.g. station calm/missing)

    monkeypatch.setattr("weather_server.external.task.fetch_external", none_fetch)

    task = asyncio.create_task(external_fetch_loop(cfg, db, store))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if calls["n"] >= 1:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls["n"] >= 1
    assert store.get() is None  # nothing stored, loop kept running


# ── persistence (ADR-0003) ─────────────────────────────────────────────────


def _obs(observed_at: datetime | None, wind: float = 3.1) -> Observation:
    return Observation(
        provider="open-meteo",
        source="open-meteo model point",
        observed_at=observed_at,
        wind_speed_ms=wind,
        wind_gust_ms=5.4,
        wind_direction_deg=212.0,
        cloud_cover_pct=40.0,
        uv_index=5.0,
    )


async def _run_loop_until(cfg, db, store, monkeypatch, fetches: list, want: int):
    """Drive external_fetch_loop through `want` fetches, then cancel it."""
    calls = {"n": 0}

    def fake_fetch(*args, **kwargs):
        i = calls["n"]
        calls["n"] += 1
        return fetches[min(i, len(fetches) - 1)]

    monkeypatch.setattr("weather_server.external.task.fetch_external", fake_fetch)
    task = asyncio.create_task(external_fetch_loop(cfg, db, store))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if calls["n"] >= want:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return calls["n"]


async def test_loop_persists_observation(tmp_path, monkeypatch) -> None:
    db = init_db(tmp_path / "w.db")
    cfg = _config({"enabled": True, "refresh_interval_seconds": 600})
    store = ExternalStore()
    at = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)

    await _run_loop_until(cfg, db, store, monkeypatch, [_obs(at)], want=1)

    rows = db.execute("SELECT * FROM external_readings").fetchall()
    assert len(rows) == 1
    assert rows[0]["wind_speed_ms"] == 3.1
    assert rows[0]["provider"] == "open-meteo"
    # Stamped with the provider's observation time, not the fetch time.
    assert rows[0]["timestamp"] == int(at.timestamp())
    assert rows[0]["observed_at"] == int(at.timestamp())


async def test_loop_does_not_persist_when_disabled(tmp_path) -> None:
    db = init_db(tmp_path / "w.db")
    cfg = _config(None)
    store = ExternalStore()
    await asyncio.wait_for(external_fetch_loop(cfg, db, store), timeout=1.0)
    assert db.execute("SELECT COUNT(*) FROM external_readings").fetchone()[0] == 0


async def test_loop_dedups_repeated_observed_at(tmp_path, monkeypatch) -> None:
    # The real failure mode: a 300s refresh against an hourly provider sees
    # the same observation ~12 times. Only one row should result.
    db = init_db(tmp_path / "w.db")
    cfg = _config({"enabled": True, "refresh_interval_seconds": 0})
    store = ExternalStore()
    at = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)

    n = await _run_loop_until(cfg, db, store, monkeypatch, [_obs(at)], want=4)

    assert n >= 4, "loop should have fetched repeatedly"
    assert db.execute("SELECT COUNT(*) FROM external_readings").fetchone()[0] == 1


async def test_loop_logs_each_new_observed_at(tmp_path, monkeypatch) -> None:
    db = init_db(tmp_path / "w.db")
    cfg = _config({"enabled": True, "refresh_interval_seconds": 0})
    store = ExternalStore()
    t0 = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    feed = [_obs(t0, 1.0), _obs(t0 + timedelta(hours=1), 2.0), _obs(t0 + timedelta(hours=2), 3.0)]

    await _run_loop_until(cfg, db, store, monkeypatch, feed, want=3)

    speeds = [
        r["wind_speed_ms"]
        for r in db.execute("SELECT * FROM external_readings ORDER BY timestamp").fetchall()
    ]
    assert speeds == [1.0, 2.0, 3.0]


async def test_loop_without_observed_at_logs_every_fetch(tmp_path, monkeypatch) -> None:
    # No provider stamp ⇒ fetch time is the only time signal, and it always
    # advances, so every successful fetch is a distinct row.
    db = init_db(tmp_path / "w.db")
    cfg = _config({"enabled": True, "refresh_interval_seconds": 0})
    store = ExternalStore()

    await _run_loop_until(cfg, db, store, monkeypatch, [_obs(None)], want=2)

    rows = db.execute("SELECT * FROM external_readings").fetchall()
    assert len(rows) >= 1
    assert all(r["observed_at"] is None for r in rows)


async def test_loop_survives_persist_failure(tmp_path, monkeypatch) -> None:
    db = init_db(tmp_path / "w.db")
    cfg = _config({"enabled": True, "refresh_interval_seconds": 600})
    store = ExternalStore()

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("weather_server.external.task.insert_external_reading", boom)

    at = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    await _run_loop_until(cfg, db, store, monkeypatch, [_obs(at)], want=1)

    # The live store still got the value; only persistence failed.
    assert store.get() is not None
