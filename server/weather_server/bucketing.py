"""Time-window resolution and bucketed aggregation for the history endpoints.

Extracted from routes/history.py so that `/api/v1/history/{sensor_id}` and
`/api/v1/external/history` share one implementation of the `bucket=auto`
heuristic. Two copies would drift, and 02-api-design.md documents exactly
one heuristic table.

Aggregation is expressed as a per-column policy rather than the single
"continuous columns" list the outdoor path used to carry, because the
external series needs `max` (a mean of gusts understates the gust) and a
circular mean (bearings do not average as scalars) alongside plain means.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException

# Both a real sqlite3.Row and the synthetic dict a bucket produces support
# keys() + [k], which is all the helpers below need.
RowLike = sqlite3.Row | dict[str, Any]

AggPolicy = Literal["mean", "max", "last", "vector_mean_deg"]

#: How each outdoor column collapses within a bucket. Columns not listed
#: default to "last" (most-recent), which is the documented behaviour for
#: discrete/state values like satellites and RSSI.
OUTDOOR_AGGREGATION: Mapping[str, AggPolicy] = {
    "temperature_c": "mean",
    "humidity_pct": "mean",
    "pressure_pa": "mean",
    "lux": "mean",
    "ir": "mean",
    "visible": "mean",
    "full_spectrum": "mean",
    "altitude_m": "mean",
    "speed_kmh": "mean",
    # GPS course is a compass bearing. Scalar-averaging 350° and 10° yields
    # 180° — the exact opposite of the truth. No include group emits
    # course_deg today, so this was dormant rather than visible; fixed here
    # rather than left as a trap for whoever charts heading first.
    "course_deg": "vector_mean_deg",
}


def parse_iso_ts(value: str, field: str) -> int:
    """Parse an ISO 8601 datetime to a UTC epoch. 400 on malformed input."""
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=("bad_request", f"invalid ISO 8601 datetime for {field!r}: {value!r}"),
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())


def resolve_window(from_: str | None, to: str | None, hours: int) -> tuple[int, int, int]:
    """Resolve the query window to (from_ts, to_ts, span_hours).

    `from`/`to` (ISO 8601) take precedence over `hours` when supplied; `to`
    defaults to now. Returns the span in whole hours so `bucket=auto` still
    works. Raises 400 on malformed timestamps or a non-positive window.
    """
    now_ts = int(datetime.now(UTC).timestamp())
    if from_ is None and to is None:
        return now_ts - hours * 3600, now_ts, hours

    to_ts = parse_iso_ts(to, "to") if to is not None else now_ts
    from_ts = parse_iso_ts(from_, "from") if from_ is not None else to_ts - hours * 3600
    if from_ts >= to_ts:
        raise HTTPException(
            status_code=400,
            detail=("bad_request", "'from' must be earlier than 'to'"),
        )
    return from_ts, to_ts, max(1, (to_ts - from_ts) // 3600)


def parse_include(value: str, valid_groups: Sequence[str]) -> set[str]:
    """Split a comma-separated `include` param, rejecting unknown groups."""
    groups = {g.strip() for g in value.split(",") if g.strip()}
    unknown = groups - set(valid_groups)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=("bad_request", f"unknown include group(s): {sorted(unknown)}"),
        )
    return groups


def resolve_bucket(bucket: str, hours: int) -> int:
    """Bucket width in seconds; 0 means "no bucketing, return raw rows"."""
    if bucket == "raw":
        return 0
    if bucket == "auto":
        if hours <= 1:
            return 0
        if hours <= 6:
            return 60
        if hours <= 24:
            return 300
        if hours <= 24 * 7:
            return 1800
        return 3600
    return int(bucket)


def circular_mean_deg(values: Sequence[float]) -> float | None:
    """Unit-vector mean of compass bearings, normalised to [0, 360).

    Returns None when the vectors cancel (e.g. exactly opposing bearings) —
    there is genuinely no mean direction in that case, and emitting an
    arbitrary one would be worse than emitting nothing.
    """
    if not values:
        return None
    sin_sum = sum(math.sin(math.radians(v)) for v in values)
    cos_sum = sum(math.cos(math.radians(v)) for v in values)
    if math.hypot(sin_sum, cos_sum) < 1e-9:
        return None
    deg = math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0
    # A due-north mean makes atan2 return a tiny *negative* angle, and
    # Python's % then yields exactly 360.0 rather than 0.0. Snap it — a
    # bearing that close to 360 is due north by any measure we care about.
    return 0.0 if deg >= 360.0 - 1e-9 else deg


def aggregate_bucket(
    rows: Sequence[RowLike],
    bucket_start: int,
    policy: Mapping[str, AggPolicy],
) -> dict[str, Any]:
    """Collapse one bucket's rows to a single synthetic row.

    The row is stamped with `bucket_start` (the floor of the bucket window),
    not the mean of the member timestamps.
    """
    last_row = rows[-1]
    agg: dict[str, Any] = {"timestamp": bucket_start}
    for k in last_row.keys():
        if k in {"id", "timestamp"}:
            continue
        how: AggPolicy = policy.get(k, "last")
        if how == "last":
            agg[k] = last_row[k]
            continue
        vals = [r[k] for r in rows if r[k] is not None]
        if not vals:
            agg[k] = None
        elif how == "mean":
            agg[k] = sum(vals) / len(vals)
        elif how == "max":
            agg[k] = max(vals)
        else:
            agg[k] = circular_mean_deg(vals)
    return agg


def bucket_rows(
    rows: Sequence[RowLike],
    bucket_seconds: int,
    policy: Mapping[str, AggPolicy],
) -> list[RowLike]:
    """Group rows into fixed windows of `bucket_seconds` and aggregate each.

    Rows must already be ordered by ascending timestamp. When no bucketing
    is requested (bucket_seconds <= 0) the rows pass through unchanged.
    """
    if not rows or bucket_seconds <= 0:
        return list(rows)
    out: list[RowLike] = []
    current_bucket: list[RowLike] = []
    current_start: int | None = None
    for row in rows:
        ts = int(row["timestamp"])
        b_start = (ts // bucket_seconds) * bucket_seconds
        if current_start is None:
            current_start = b_start
        if b_start != current_start:
            out.append(aggregate_bucket(current_bucket, current_start, policy))
            current_bucket = []
            current_start = b_start
        current_bucket.append(row)
    if current_bucket and current_start is not None:
        out.append(aggregate_bucket(current_bucket, current_start, policy))
    return out
