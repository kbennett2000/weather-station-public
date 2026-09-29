"""Plausibility bounds (ADR-0004): an out-of-range value is treated as
missing, both when a reading arrives and when a stored row is read back."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import BRANDING_EXAMPLE, FIXTURE_SRC, TOML_TEMPLATE
from weather_server import plausibility
from weather_server.db import init_db, insert_outdoor_reading

RANGES = sorted(plausibility.PLAUSIBLE_RANGES.items())


@pytest.mark.parametrize(("key", "bounds"), RANGES)
def test_values_outside_bounds_are_dropped(key: str, bounds: tuple[float, float]) -> None:
    lo, hi = bounds
    for bad in (lo - 1, hi + 1):
        payload = {key: bad, "rssi_dbm": -62}
        plausibility.drop_implausible(payload)
        assert key not in payload, f"{key}={bad} should be refused"
        assert payload["rssi_dbm"] == -62


@pytest.mark.parametrize(("key", "bounds"), RANGES)
def test_values_at_bounds_are_kept(key: str, bounds: tuple[float, float]) -> None:
    for ok in bounds:
        payload = {key: ok}
        plausibility.drop_implausible(payload)
        assert payload == {key: ok}


@pytest.fixture
def client_with_gps_sentinel_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """A DB holding a real reading plus a stored cold-boot TinyGPS row, as
    on the Pi before the ingestion fix (e.g. row 165424 on Sep 18)."""
    from weather_server.main import create_app

    db_path = tmp_path / "weather.db"
    conn = init_db(db_path)
    now_ts = int(datetime.now(UTC).timestamp())
    good = {
        "temperature_c": 18.0,
        "humidity_pct": 40.0,
        "pressure_pa": 80700.0,
        "latitude": 39.433,
        "longitude": -104.519,
        "altitude_m": 1970.0,
    }
    no_fix = {
        **good,
        "latitude": 1000.0,
        "longitude": 1000.0,
        "altitude_m": 10_000_000.0,
        "satellites": 255,
        "speed_kmh": 18_500_000.0,
        "course_deg": 10_000_000.0,
    }
    insert_outdoor_reading(conn, now_ts - 6 * 3600, good)
    insert_outdoor_reading(conn, now_ts - 3 * 3600, no_fix)
    conn.close()

    fixture_dir = tmp_path / "fixtures"
    shutil.copytree(FIXTURE_SRC, fixture_dir)
    cfg_path = tmp_path / "weather.toml"
    cfg_path.write_text(
        TOML_TEMPLATE.format(
            db_path=str(db_path),
            fixture_dir=str(fixture_dir),
            branding_path=str(BRANDING_EXAMPLE),
        )
    )
    monkeypatch.setenv("WEATHER_CONFIG", str(cfg_path))

    with TestClient(create_app()) as tc:
        yield tc


def test_history_ignores_stored_gps_sentinels(client_with_gps_sentinel_row: TestClient) -> None:
    # The stored 10,000 km altitude used to become a ~1e129 hPa sea-level
    # pressure spike, or an OverflowError (HTTP 500) when alone in a bucket.
    r = client_with_gps_sentinel_row.get("/api/v1/history/outdoor?hours=168")
    assert r.status_code == 200
    pressures = [
        row["pressure_sealevel_hpa"]
        for row in r.json()["rows"]
        if row["pressure_sealevel_hpa"] is not None
    ]
    assert pressures
    assert all(900 < p < 1100 for p in pressures), pressures


@pytest.mark.parametrize("period", ["7d", "30d"])
def test_summary_ignores_stored_gps_sentinels(
    client_with_gps_sentinel_row: TestClient, period: str
) -> None:
    r = client_with_gps_sentinel_row.get(f"/api/v1/summary/outdoor?period={period}")
    assert r.status_code == 200
