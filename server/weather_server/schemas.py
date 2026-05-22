"""Pydantic response models for the weather API.

These models are the runtime expression of the contract in
docs/design/02-api-design.md. FastAPI uses them to drive both response
validation and the OpenAPI schema at /docs.

Field provenance taxonomy from the API design doc:
- RAW           — direct sensor reading
- CALIBRATED    — raw + offset
- D-READING     — derived from a single reading
- D-LOCATION    — derived from GPS coords
- D-TIME        — derived from clock + location
- META          — server bookkeeping
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ── SensorReading ────────────────────────────────────────────────────────────


class RawReading(_StrictModel):
    temperature_c: float | None = None
    humidity_pct: float | None = None
    pressure_pa: float | None = None
    lux: float | None = None
    ir: int | None = None
    visible: int | None = None
    full: int | None = None


class CalibrationBlock(_StrictModel):
    temp_offset_c: float | None = None


class DerivedReading(_StrictModel):
    temperature_c: float | None = None
    temperature_f: float | None = None
    dewpoint_c: float | None = None
    dewpoint_f: float | None = None
    absolute_humidity_g_m3: float | None = None
    pressure_station_hpa: float | None = None
    pressure_station_inhg: float | None = None
    pressure_sealevel_hpa: float | None = None
    pressure_sealevel_inhg: float | None = None


class LocationBlock(_StrictModel):
    lat: float | None = None
    lon: float | None = None
    altitude_m: float | None = None
    altitude_ft: float | None = None
    satellites: int | None = None
    speed_kmh: float | None = None
    course_deg: float | None = None
    dms: str | None = None
    maidenhead: str | None = None


class DeviceBlock(_StrictModel):
    rssi_dbm: int | None = None
    uptime_s: int | None = None
    free_heap_bytes: int | None = None


class SensorReading(_StrictModel):
    sensor_id: str
    role: str
    online: bool
    reading_timestamp: datetime | None = None
    age_seconds: float | None = None

    raw: RawReading = Field(default_factory=RawReading)
    calibration: CalibrationBlock = Field(default_factory=CalibrationBlock)
    derived: DerivedReading = Field(default_factory=DerivedReading)
    location: LocationBlock | None = None
    device: DeviceBlock = Field(default_factory=DeviceBlock)


# ── Astronomy ────────────────────────────────────────────────────────────────


class ReferenceLocation(_StrictModel):
    lat: float | None = None
    lon: float | None = None
    source: str  # "outdoor_sensor" | "config_default" | "query_override"


class SunBlock(_StrictModel):
    altitude_deg: float | None = None
    azimuth_deg: float | None = None
    is_daytime: bool | None = None
    sunrise: datetime | None = None
    sunset: datetime | None = None
    solar_noon: datetime | None = None
    dawn: datetime | None = None
    dusk: datetime | None = None
    day_length_seconds: float | None = None
    seconds_to_sunset: float | None = None
    seconds_to_sunrise: float | None = None


class MoonBlock(_StrictModel):
    altitude_deg: float | None = None
    azimuth_deg: float | None = None
    distance_km: float | None = None
    illumination_pct: float | None = None
    phase_name: str | None = None
    phase_icon: str | None = None
    moonrise: datetime | None = None
    moonset: datetime | None = None
    always_up: bool | None = None
    always_down: bool | None = None


class Astronomy(_StrictModel):
    server_time: datetime
    local_time: datetime | None = None
    timezone: str
    reference_location: ReferenceLocation
    sun: SunBlock
    moon: MoonBlock


# ── Endpoint responses ───────────────────────────────────────────────────────


class CurrentResponse(_StrictModel):
    server_time: datetime
    sensors: dict[str, SensorReading]
    astronomy: Astronomy


class CurrentSensorResponse(_StrictModel):
    server_time: datetime
    sensor: SensorReading
    astronomy: Astronomy


class HistoryRow(_StrictModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    timestamp: datetime


class HistoryResponse(_StrictModel):
    sensor_id: str
    from_: datetime = Field(serialization_alias="from", validation_alias="from")
    to: datetime
    bucket_seconds: int
    row_count: int
    rows: list[HistoryRow]

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class SensorListEntry(_StrictModel):
    sensor_id: str
    role: str
    ip: str
    has_gps: bool
    has_light: bool
    logged: bool
    last_seen: datetime | None
    age_seconds: float | None
    online: bool


class SensorListResponse(_StrictModel):
    server_time: datetime
    sensors: list[SensorListEntry]


class AstronomyResponse(_StrictModel):
    server_time: datetime
    astronomy: Astronomy


class HealthSensorEntry(_StrictModel):
    sensor_id: str
    online: bool
    age_seconds: float | None


class HealthLoggerEntry(_StrictModel):
    sensor_id: str
    last_write_seconds_ago: float | None
    ok: bool


class HealthResponse(_StrictModel):
    ok: bool
    server_time: datetime
    db_reachable: bool
    sensors: list[HealthSensorEntry]
    loggers: list[HealthLoggerEntry]


# ── Errors ───────────────────────────────────────────────────────────────────


class ErrorBody(_StrictModel):
    code: str
    message: str
    details: dict[str, str] = Field(default_factory=dict)


class ErrorResponse(_StrictModel):
    error: ErrorBody
