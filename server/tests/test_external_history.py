"""GET /api/v1/external/history — the logged regional series (ADR-0003).

Rows are seeded straight into external_readings rather than driven through
the fetch task, so these tests never touch the network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from weather_server import schemas
from weather_server.db import insert_external_reading

_NOW = datetime.now(UTC)


def _seed(client: TestClient, samples: list[dict], provider: str = "open-meteo") -> None:
    db = client.app.state.db
    for i, s in enumerate(samples):
        ts = int((_NOW - timedelta(minutes=len(samples) - i)).timestamp())
        insert_external_reading(
            db,
            ts,
            {
                "observed_at": ts,
                "provider": provider,
                "source": "test",
                **s,
            },
        )


def test_disabled_feed_returns_200_with_empty_rows(client: TestClient) -> None:
    # Absence of a feed is a normal state, not a 404 — a 404 would be
    # indistinguishable from a bad URL on the client side.
    r = client.get("/api/v1/external/history?hours=24")
    assert r.status_code == 200
    parsed = schemas.ExternalHistoryResponse.model_validate(r.json())
    assert parsed.enabled is False
    assert parsed.row_count == 0
    assert parsed.rows == []


def test_disabled_feed_ignores_logged_rows(client: TestClient) -> None:
    # Even if a table has rows from a previously-enabled install, a disabled
    # feed reports nothing — the config is the source of truth.
    _seed(client, [{"wind_speed_ms": 3.0}])
    r = client.get("/api/v1/external/history?hours=24")
    assert r.status_code == 200
    assert r.json()["row_count"] == 0


def test_enabled_but_empty_returns_zero_rows(external_client: TestClient) -> None:
    r = external_client.get("/api/v1/external/history?hours=24")
    assert r.status_code == 200
    parsed = schemas.ExternalHistoryResponse.model_validate(r.json())
    assert parsed.enabled is True
    assert parsed.row_count == 0


def test_returns_logged_rows_with_converted_units(external_client: TestClient) -> None:
    sample = {"wind_speed_ms": 10.0, "wind_gust_ms": 20.0, "wind_direction_deg": 90.0}
    _seed(external_client, [sample])
    r = external_client.get("/api/v1/external/history?hours=24&bucket=raw")
    assert r.status_code == 200
    parsed = schemas.ExternalHistoryResponse.model_validate(r.json())
    assert parsed.row_count == 1
    row = parsed.rows[0].model_dump()
    assert row["wind_speed_ms"] == 10.0
    assert row["wind_speed_kmh"] == 36.0
    assert row["wind_speed_mph"] == 22.4
    assert row["wind_speed_kt"] == 19.4
    assert row["wind_gust_mph"] == 44.7
    assert row["wind_direction_cardinal"] == "E"


def test_provider_reported_at_top_level(external_client: TestClient) -> None:
    _seed(external_client, [{"wind_speed_ms": 3.0}], provider="nws")
    r = external_client.get("/api/v1/external/history?hours=24")
    parsed = schemas.ExternalHistoryResponse.model_validate(r.json())
    assert parsed.provider == "nws"
    assert parsed.source == "test"


def test_default_include_is_wind_only(external_client: TestClient) -> None:
    _seed(external_client, [{"wind_speed_ms": 3.0, "cloud_cover_pct": 40.0, "uv_index": 5.0}])
    r = external_client.get("/api/v1/external/history?hours=24&bucket=raw")
    row = r.json()["rows"][0]
    assert "wind_speed_mph" in row
    assert "cloud_cover_pct" not in row
    assert "uv_index" not in row


def test_include_sky_adds_cloud_and_uv(external_client: TestClient) -> None:
    _seed(external_client, [{"wind_speed_ms": 3.0, "cloud_cover_pct": 40.0, "uv_index": 5.0}])
    r = external_client.get("/api/v1/external/history?hours=24&bucket=raw&include=wind,sky")
    row = r.json()["rows"][0]
    assert row["cloud_cover_pct"] == 40.0
    assert row["uv_index"] == 5.0
    assert "wind_speed_mph" in row


def test_bucketing_means_speed_and_peaks_gust(external_client: TestClient) -> None:
    _seed(
        external_client,
        [
            {"wind_speed_ms": 2.0, "wind_gust_ms": 4.0},
            {"wind_speed_ms": 4.0, "wind_gust_ms": 12.0},
            {"wind_speed_ms": 6.0, "wind_gust_ms": 6.0},
        ],
    )
    r = external_client.get("/api/v1/external/history?hours=24&bucket=3600")
    parsed = schemas.ExternalHistoryResponse.model_validate(r.json())
    assert parsed.bucket_seconds == 3600
    row = parsed.rows[-1].model_dump()
    assert row["wind_speed_ms"] == 4.0  # mean of 2, 4, 6
    assert row["wind_gust_ms"] == 12.0  # peak, NOT the 7.33 mean


def test_bucketing_uses_circular_mean_for_direction(external_client: TestClient) -> None:
    # Scalar-averaging 350 and 10 gives 180 — due south instead of north.
    _seed(
        external_client,
        [{"wind_direction_deg": 350.0}, {"wind_direction_deg": 10.0}],
    )
    r = external_client.get("/api/v1/external/history?hours=24&bucket=3600")
    row = r.json()["rows"][-1]
    assert row["wind_direction_deg"] == 0.0
    assert row["wind_direction_cardinal"] == "N"


def test_bad_include_group_returns_400(external_client: TestClient) -> None:
    r = external_client.get("/api/v1/external/history?include=wind,nonsense")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


def test_bad_from_returns_400(external_client: TestClient) -> None:
    r = external_client.get("/api/v1/external/history?from=yesterday")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


def test_from_after_to_returns_400(external_client: TestClient) -> None:
    r = external_client.get(
        "/api/v1/external/history?from=2026-05-22T00:00:00Z&to=2026-05-21T00:00:00Z"
    )
    assert r.status_code == 400


def test_window_excludes_older_rows(external_client: TestClient) -> None:
    db = external_client.app.state.db
    old = int((_NOW - timedelta(days=30)).timestamp())
    recent = int((_NOW - timedelta(minutes=5)).timestamp())
    insert_external_reading(db, old, {"provider": "open-meteo", "wind_speed_ms": 1.0})
    insert_external_reading(db, recent, {"provider": "open-meteo", "wind_speed_ms": 9.0})

    r = external_client.get("/api/v1/external/history?hours=24&bucket=raw")
    parsed = schemas.ExternalHistoryResponse.model_validate(r.json())
    assert parsed.row_count == 1
    assert parsed.rows[0].model_dump()["wind_speed_ms"] == 9.0


def test_endpoint_appears_in_openapi(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/external/history" in paths


def test_history_external_path_still_404s_as_a_sensor(client: TestClient) -> None:
    # Guards the path choice: /api/v1/history/external is owned by the
    # {sensor_id} route, which is exactly why the endpoint lives elsewhere.
    r = client.get("/api/v1/history/external")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "sensor_not_found"
