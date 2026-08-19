"""GET /api/v1/history/{sensor_id}.

Only `outdoor` is logged; any other sensor_id returns 404
`history_not_available` per 02-api-design.md.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from .. import db as db_module
from ..bucketing import (
    OUTDOOR_AGGREGATION,
    bucket_rows,
    parse_include,
    resolve_bucket,
    resolve_window,
)
from ..responses import HISTORY_GROUPS, build_history_row
from ..schemas import HistoryResponse, HistoryRow

router = APIRouter()


BucketLiteral = Literal["raw", "60", "300", "900", "3600", "auto"]


@router.get(
    "/api/v1/history/{sensor_id}",
    response_model=HistoryResponse,
    response_model_exclude_none=False,
)
async def get_history(
    sensor_id: str,
    request: Request,
    hours: int = Query(24, ge=1, le=24 * 365),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None, alias="to"),
    bucket: BucketLiteral = "auto",
    include: str = "weather",
) -> HistoryResponse:
    config = request.app.state.config
    db = request.app.state.db

    sensor_cfg = config.sensor_by_id(sensor_id)
    if sensor_cfg is None:
        raise HTTPException(status_code=404, detail=("sensor_not_found", sensor_id))
    if sensor_cfg.role != "outdoor":
        raise HTTPException(status_code=404, detail=("history_not_available", sensor_id))

    include_groups = parse_include(include, list(HISTORY_GROUPS))
    from_ts, to_ts, span_hours = resolve_window(from_, to, hours)
    from_dt = datetime.fromtimestamp(from_ts, tz=UTC)
    to_dt = datetime.fromtimestamp(to_ts, tz=UTC)

    bucket_seconds = resolve_bucket(bucket, span_hours)

    raw_rows = db_module.outdoor_readings_in_range(db, from_ts, to_ts)
    bucketed = (
        bucket_rows(raw_rows, bucket_seconds, OUTDOOR_AGGREGATION)
        if bucket_seconds > 0
        else raw_rows
    )

    rows: list[HistoryRow] = [
        HistoryRow.model_validate(build_history_row(row, sensor_cfg, include_groups))
        for row in bucketed
    ]

    return HistoryResponse(
        sensor_id=sensor_id,
        from_=from_dt,
        to=to_dt,
        bucket_seconds=bucket_seconds,
        row_count=len(rows),
        rows=rows,
    )
