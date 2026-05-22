"""End-to-end endpoint tests using the FastAPI TestClient.

These tests start the app with the example config + fixture dir and
exercise every endpoint, asserting response shape against the Pydantic
models (which already mirror 02-api-design.md exactly) plus the
documented error cases.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from weather_server import schemas

SERVER_ROOT = Path(__file__).parent.parent
FIXTURE_SRC = SERVER_ROOT / "fixtures"
TOML_TEMPLATE = """
[server]
host = "127.0.0.1"
port = 8005
db_path = "{db_path}"

[logger]
interval_seconds = 60
http_timeout_seconds = 10

[cache]
ttl_seconds = 5

[development]
fixture_dir = "{fixture_dir}"

[[sensors]]
id = "outdoor"
role = "outdoor"
ip = "192.168.1.60"
has_gps = true
has_light = true
online_threshold_seconds = 120
temp_offset_c = -0.5
fallback_altitude_m = 1609.3

[[sensors]]
id = "indoor"
role = "indoor"
ip = "192.168.1.61"
has_gps = false
has_light = false
online_threshold_seconds = 120
temp_offset_c = 0.0

[[sensors]]
id = "basement"
role = "indoor"
ip = "192.168.1.63"
has_gps = false
has_light = false
online_threshold_seconds = 300
temp_offset_c = 0.0
"""


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    fixture_dir = tmp_path / "fixtures"
    shutil.copytree(FIXTURE_SRC, fixture_dir)

    db_path = tmp_path / "weather.db"
    cfg = tmp_path / "weather.toml"
    cfg.write_text(
        TOML_TEMPLATE.format(db_path=str(db_path), fixture_dir=str(fixture_dir))
    )

    monkeypatch.setenv("WEATHER_CONFIG", str(cfg))

    # Re-import to pick up the env var via lifespan.
    from weather_server.main import create_app

    app = create_app()
    with TestClient(app) as tc:
        yield tc


def test_current_endpoint_returns_documented_shape(client: TestClient) -> None:
    r = client.get("/api/v1/current")
    assert r.status_code == 200
    parsed = schemas.CurrentResponse.model_validate(r.json())
    assert "outdoor" in parsed.sensors
    assert "indoor" in parsed.sensors
    assert "basement" in parsed.sensors

    outdoor = parsed.sensors["outdoor"]
    assert outdoor.online is True
    # Pressure quadruple all present.
    d = outdoor.derived
    assert d.pressure_station_hpa is not None
    assert d.pressure_station_inhg is not None
    assert d.pressure_sealevel_hpa is not None
    assert d.pressure_sealevel_inhg is not None

    # Location block only on outdoor.
    assert outdoor.location is not None
    assert outdoor.location.maidenhead is not None
    assert parsed.sensors["indoor"].location is None

    # Astronomy populated.
    assert parsed.astronomy.timezone in ("America/Denver", "UTC")
    assert parsed.astronomy.reference_location.source == "outdoor_sensor"


def test_current_one_outdoor(client: TestClient) -> None:
    r = client.get("/api/v1/current/outdoor")
    assert r.status_code == 200
    parsed = schemas.CurrentSensorResponse.model_validate(r.json())
    assert parsed.sensor.sensor_id == "outdoor"


def test_current_one_indoor(client: TestClient) -> None:
    r = client.get("/api/v1/current/indoor")
    assert r.status_code == 200
    parsed = schemas.CurrentSensorResponse.model_validate(r.json())
    assert parsed.sensor.role == "indoor"
    assert parsed.sensor.location is None


def test_current_one_unknown_returns_404_with_error_envelope(client: TestClient) -> None:
    r = client.get("/api/v1/current/kitchen")
    assert r.status_code == 404
    body = r.json()
    schemas.ErrorResponse.model_validate(body)
    assert body["error"]["code"] == "sensor_not_found"


def test_history_outdoor_returns_rows(client: TestClient) -> None:
    r = client.get("/api/v1/history/outdoor?hours=24")
    assert r.status_code == 200
    parsed = schemas.HistoryResponse.model_validate(r.json())
    assert parsed.sensor_id == "outdoor"
    assert parsed.row_count == len(parsed.rows)
    if parsed.rows:
        # default include is "weather": no lux on the row.
        sample = parsed.rows[0].model_dump()
        assert "lux" not in sample
        assert "temperature_c" in sample


def test_history_include_light_adds_lux(client: TestClient) -> None:
    r = client.get("/api/v1/history/outdoor?hours=24&include=weather,light")
    assert r.status_code == 200
    parsed = schemas.HistoryResponse.model_validate(r.json())
    if parsed.rows:
        sample = parsed.rows[0].model_dump()
        assert "lux" in sample


def test_history_indoor_returns_404_history_not_available(client: TestClient) -> None:
    r = client.get("/api/v1/history/indoor")
    assert r.status_code == 404
    body = r.json()
    schemas.ErrorResponse.model_validate(body)
    assert body["error"]["code"] == "history_not_available"


def test_history_unknown_sensor_returns_404_sensor_not_found(client: TestClient) -> None:
    r = client.get("/api/v1/history/kitchen")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "sensor_not_found"


def test_history_bad_include_group_returns_400(client: TestClient) -> None:
    r = client.get("/api/v1/history/outdoor?include=weather,nonsense")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


def test_sensors_endpoint_lists_all_three(client: TestClient) -> None:
    r = client.get("/api/v1/sensors")
    assert r.status_code == 200
    parsed = schemas.SensorListResponse.model_validate(r.json())
    ids = [s.sensor_id for s in parsed.sensors]
    assert set(ids) == {"outdoor", "indoor", "basement"}
    outdoor_entry = next(s for s in parsed.sensors if s.sensor_id == "outdoor")
    assert outdoor_entry.logged is True
    indoor_entry = next(s for s in parsed.sensors if s.sensor_id == "indoor")
    assert indoor_entry.logged is False


def test_astronomy_endpoint(client: TestClient) -> None:
    r = client.get("/api/v1/astronomy")
    assert r.status_code == 200
    parsed = schemas.AstronomyResponse.model_validate(r.json())
    assert parsed.astronomy.reference_location.source == "outdoor_sensor"


def test_astronomy_with_lat_lon_override(client: TestClient) -> None:
    r = client.get("/api/v1/astronomy?lat=51.5074&lon=-0.1278")
    assert r.status_code == 200
    parsed = schemas.AstronomyResponse.model_validate(r.json())
    assert parsed.astronomy.reference_location.source == "query_override"
    assert parsed.astronomy.timezone == "Europe/London"


def test_health_endpoint(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    parsed = schemas.HealthResponse.model_validate(r.json())
    assert parsed.db_reachable is True
    assert any(le.sensor_id == "outdoor" for le in parsed.loggers)
    assert len(parsed.loggers) == 1  # only outdoor is logged


def test_offline_sensor_returns_503_when_never_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If indoor.json marks the sensor offline AND there's no last_seen,
    GET /api/v1/current/indoor returns 503 sensor_no_data."""
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    shutil.copy(FIXTURE_SRC / "outdoor.json", fixture_dir / "outdoor.json")
    (fixture_dir / "indoor.json").write_text('{"temperature_c": 22.0, "offline": true}')
    (fixture_dir / "basement.json").write_text('{"temperature_c": 18.0, "offline": true}')

    db_path = tmp_path / "weather.db"
    cfg = tmp_path / "weather.toml"
    cfg.write_text(TOML_TEMPLATE.format(db_path=str(db_path), fixture_dir=str(fixture_dir)))
    monkeypatch.setenv("WEATHER_CONFIG", str(cfg))

    from weather_server.main import create_app

    with TestClient(create_app()) as tc:
        r = tc.get("/api/v1/current/indoor")
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "sensor_no_data"


def test_openapi_docs_render(client: TestClient) -> None:
    r = client.get("/docs")
    assert r.status_code == 200
    assert b"swagger" in r.content.lower()
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    paths = schema["paths"]
    for expected in (
        "/api/v1/current",
        "/api/v1/current/{sensor_id}",
        "/api/v1/history/{sensor_id}",
        "/api/v1/sensors",
        "/api/v1/astronomy",
        "/api/v1/health",
    ):
        assert expected in paths
