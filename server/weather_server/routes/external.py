"""Internet-sourced regional conditions (EXTERNAL provenance).

GET /api/v1/external mirrors /api/v1/astronomy: the same block that
/api/v1/current embeds, exposed standalone for consumers that only want
regional data. Returns ``external: null`` when the feed is disabled or no
data has arrived yet.

GET /api/v1/external/history serves the logged series from
external_readings (ADR-0003). It lives under the `external` prefix rather
than as /api/v1/history/external because that path is owned by
/api/v1/history/{sensor_id}, which resolves the segment against the
configured sensors — and the internet feed is not a sensor.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Query, Request

from .. import db as db_module
from ..bucketing import bucket_rows, parse_include, resolve_bucket, resolve_window
from ..responses import (
    EXTERNAL_AGGREGATION,
    EXTERNAL_HISTORY_GROUPS,
    build_external,
    build_external_history_row,
    build_outdoor_reading_from_db_row,
    external_stale_after,
    utc_now,
)
from ..schemas import ExternalHistoryResponse, ExternalHistoryRow, ExternalResponse

router = APIRouter()

BucketLiteral = Literal["raw", "60", "300", "900", "3600", "auto"]


@router.get(
    "/api/v1/external",
    response_model=ExternalResponse,
    response_model_exclude_none=False,
)
async def get_external(request: Request) -> ExternalResponse:
    server_time = utc_now()
    config = request.app.state.config
    db = request.app.state.db

    # The fused indices (wind chill etc.) need the local outdoor reading.
    outdoor_reading = None
    if config.outdoor is not None:
        row = db_module.latest_outdoor_reading(db)
        if row is not None:
            outdoor_reading = build_outdoor_reading_from_db_row(config.outdoor, row, server_time)

    external = build_external(
        request.app.state.external_store.get(),
        server_time,
        stale_after_seconds=external_stale_after(config),
        outdoor_reading=outdoor_reading,
    )
    return ExternalResponse(server_time=server_time, external=external)


@router.get(
    "/api/v1/external/history",
    response_model=ExternalHistoryResponse,
    response_model_exclude_none=False,
)
async def get_external_history(
    request: Request,
    hours: int = Query(24, ge=1, le=24 * 365),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None, alias="to"),
    bucket: BucketLiteral = "auto",
    include: str = "wind",
) -> ExternalHistoryResponse:
    config = request.app.state.config
    db = request.app.state.db

    include_groups = parse_include(include, list(EXTERNAL_HISTORY_GROUPS))
    from_ts, to_ts, span_hours = resolve_window(from_, to, hours)
    bucket_seconds = resolve_bucket(bucket, span_hours)

    # A disabled feed is a normal state, not an error: answer 200 with an
    # empty series and enabled=false so the client can tell "this install
    # has no internet feed" from "the feed is on but hasn't logged yet".
    raw_rows = (
        db_module.external_readings_in_range(db, from_ts, to_ts) if config.external.enabled else []
    )
    bucketed = (
        bucket_rows(raw_rows, bucket_seconds, EXTERNAL_AGGREGATION)
        if bucket_seconds > 0
        else raw_rows
    )

    rows = [
        ExternalHistoryRow.model_validate(build_external_history_row(row, include_groups))
        for row in bucketed
    ]

    last = raw_rows[-1] if raw_rows else None
    return ExternalHistoryResponse(
        from_=datetime.fromtimestamp(from_ts, tz=UTC),
        to=datetime.fromtimestamp(to_ts, tz=UTC),
        bucket_seconds=bucket_seconds,
        row_count=len(rows),
        enabled=config.external.enabled,
        provider=last["provider"] if last is not None else None,
        source=last["source"] if last is not None else None,
        rows=rows,
    )
