"""History bucketing, window resolution and aggregation.

These were private helpers in routes/history.py with no direct coverage —
the endpoint tests only ever exercised them incidentally. Pinned here first
so the extraction into weather_server/bucketing.py is provably behaviour-
preserving.

Rows are plain dicts: both _bucket_rows and _aggregate_bucket only need
keys() + [k], which sqlite3.Row and dict both provide.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from weather_server.routes.history import (
    _aggregate_bucket,
    _bucket_rows,
    _parse_iso_ts,
    _resolve_bucket,
    _resolve_window,
)


def row(ts: int, **cols: Any) -> dict[str, Any]:
    return {"id": ts, "timestamp": ts, **cols}


# ── bucket=auto heuristic ───────────────────────────────────────────────────
# Mirrors the table in docs/design/02-api-design.md. Note that `auto` can
# return 1800, which is NOT in the BucketLiteral enum, and never returns 900,
# which is only reachable as an explicit ?bucket=900. That divergence is
# deliberate and documented.


@pytest.mark.parametrize(
    ("hours", "expected"),
    [
        (1, 0),
        (2, 60),
        (6, 60),
        (7, 300),
        (24, 300),
        (25, 1800),
        (168, 1800),
        (169, 3600),
        (24 * 365, 3600),
    ],
)
def test_resolve_bucket_auto_thresholds(hours: int, expected: int) -> None:
    assert _resolve_bucket("auto", hours) == expected


def test_resolve_bucket_raw_is_zero() -> None:
    assert _resolve_bucket("raw", 24) == 0


@pytest.mark.parametrize("value", ["60", "300", "900", "3600"])
def test_resolve_bucket_explicit_values_pass_through(value: str) -> None:
    assert _resolve_bucket(value, 24) == int(value)


# ── window resolution ──────────────────────────────────────────────────────


def test_resolve_window_defaults_to_hours_back_from_now() -> None:
    from_ts, to_ts, span = _resolve_window(None, None, 24)
    assert to_ts - from_ts == 24 * 3600
    assert span == 24
    assert abs(to_ts - int(datetime.now(UTC).timestamp())) < 5


def test_resolve_window_from_to_overrides_hours() -> None:
    from_ts, to_ts, span = _resolve_window(
        "2026-05-21T00:00:00Z", "2026-05-22T00:00:00Z", hours=999
    )
    assert to_ts - from_ts == 24 * 3600
    assert span == 24


def test_resolve_window_to_only_uses_hours_back_from_to() -> None:
    from_ts, to_ts, span = _resolve_window(None, "2026-05-22T00:00:00Z", hours=6)
    assert to_ts - from_ts == 6 * 3600
    assert span == 6


def test_resolve_window_accepts_naive_datetime_as_utc() -> None:
    aware, _, _ = _resolve_window("2026-05-21T00:00:00Z", "2026-05-22T00:00:00Z", 24)
    naive, _, _ = _resolve_window("2026-05-21T00:00:00", "2026-05-22T00:00:00", 24)
    assert aware == naive


def test_resolve_window_sub_hour_span_floors_to_one() -> None:
    # max(1, ...) keeps bucket=auto sane for windows under an hour.
    _, _, span = _resolve_window("2026-05-21T00:00:00Z", "2026-05-21T00:10:00Z", 24)
    assert span == 1


def test_resolve_window_rejects_from_after_to() -> None:
    with pytest.raises(HTTPException) as exc:
        _resolve_window("2026-05-22T00:00:00Z", "2026-05-21T00:00:00Z", 24)
    assert exc.value.status_code == 400


def test_resolve_window_rejects_equal_from_and_to() -> None:
    with pytest.raises(HTTPException) as exc:
        _resolve_window("2026-05-21T00:00:00Z", "2026-05-21T00:00:00Z", 24)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("bad", ["not-a-date", "2026-13-01T00:00:00Z", ""])
def test_parse_iso_ts_rejects_malformed(bad: str) -> None:
    with pytest.raises(HTTPException) as exc:
        _parse_iso_ts(bad, "from")
    assert exc.value.status_code == 400


def test_parse_iso_ts_accepts_z_suffix() -> None:
    assert _parse_iso_ts("1970-01-01T00:00:00Z", "from") == 0


# ── grouping ───────────────────────────────────────────────────────────────


def test_bucket_rows_passthrough_when_bucket_is_zero() -> None:
    rows = [row(0), row(30)]
    assert _bucket_rows(rows, 0) is rows


def test_bucket_rows_passthrough_when_empty() -> None:
    assert _bucket_rows([], 300) == []


def test_bucket_rows_groups_on_floor_boundary() -> None:
    # 300s buckets: 0-299 → one bucket, 300-599 → the next.
    rows = [row(0), row(150), row(299), row(300), row(599), row(600)]
    out = _bucket_rows(rows, 300)
    assert [b["timestamp"] for b in out] == [0, 300, 600]


def test_bucket_timestamp_is_bucket_start_not_mean() -> None:
    # The docstring says "mean timestamp"; the code floors to the bucket
    # start. The floor is the correct/intended behaviour — pinned here so a
    # future docstring cleanup doesn't "fix" the code instead. (The mean of
    # 310 and 590 would be 450, which is not a bucket boundary.)
    out = _bucket_rows([row(310), row(590)], 300)
    assert len(out) == 1
    assert out[0]["timestamp"] == 300


def test_bucket_rows_single_row_still_aggregates() -> None:
    out = _bucket_rows([row(42, temperature_c=18.0)], 300)
    assert len(out) == 1
    assert out[0]["timestamp"] == 0
    assert out[0]["temperature_c"] == 18.0


# ── aggregation ────────────────────────────────────────────────────────────


def test_aggregate_means_continuous_columns() -> None:
    rows = [
        row(0, temperature_c=10.0, humidity_pct=40.0, pressure_pa=84000.0),
        row(1, temperature_c=20.0, humidity_pct=60.0, pressure_pa=85000.0),
    ]
    agg = _aggregate_bucket(rows, 0)
    assert agg["temperature_c"] == 15.0
    assert agg["humidity_pct"] == 50.0
    assert agg["pressure_pa"] == 84500.0


def test_aggregate_takes_most_recent_for_discrete_columns() -> None:
    rows = [row(0, satellites=4, rssi_dbm=-70), row(1, satellites=9, rssi_dbm=-55)]
    agg = _aggregate_bucket(rows, 0)
    assert agg["satellites"] == 9
    assert agg["rssi_dbm"] == -55


def test_aggregate_ignores_nulls_in_mean() -> None:
    rows = [row(0, temperature_c=10.0), row(1, temperature_c=None), row(2, temperature_c=20.0)]
    assert _aggregate_bucket(rows, 0)["temperature_c"] == 15.0


def test_aggregate_all_null_continuous_column_yields_none() -> None:
    rows = [row(0, temperature_c=None), row(1, temperature_c=None)]
    assert _aggregate_bucket(rows, 0)["temperature_c"] is None


def test_aggregate_drops_id_and_stamps_bucket_start() -> None:
    agg = _aggregate_bucket([row(7, temperature_c=1.0)], 300)
    assert agg["timestamp"] == 300
    assert "id" not in agg
