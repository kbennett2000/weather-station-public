"""Physical plausibility bounds for sensor readings (ADR-0004).

A value outside its range is a sensor or firmware fault, not weather, and
is treated as missing — only that field, the rest of the reading stands.
The same table is enforced at both boundaries:

- **Ingestion** (`wire_format`): `drop_implausible()` removes the key
  before the payload is logged or served.
- **Read-back** (`db`): stored rows are filtered in the SELECT, so rows
  logged before a bound existed (e.g. the TinyGPS "no fix" sentinels,
  altitude 10,000,000 m) read as missing while the DB itself stays raw.

Keys are SensorPayload keys, which are also the `outdoor_readings`
column names. Bounds are inclusive.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    # BME280. Temperature is wider than any inhabited-Earth weather but
    # still admits a sun-baked housing (46 °C has been logged, legitimately).
    "temperature_c": (-50.0, 60.0),
    "humidity_pct": (0.0, 100.0),
    "pressure_pa": (30_000.0, 110_000.0),  # 300–1100 hPa, as the sketch checks
    # TSL2591. Nothing outdoors is brighter than direct sun (~120k lux);
    # ir/visible are 16-bit ADC channels and full is their sum.
    "lux": (0.0, 120_000.0),
    "ir": (0, 65_535),
    "visible": (0, 65_535),
    "full_spectrum": (0, 131_070),
    # NEO-6M via TinyGPS, whose pre-fix sentinels (lat/lon 1000, altitude
    # 1e7 m, speed ~1.85e7 km/h, course 1e7°, 255 satellites) all fall out.
    "latitude": (-90.0, 90.0),
    "longitude": (-180.0, 180.0),
    "altitude_m": (-500.0, 9000.0),
    "speed_kmh": (0.0, 1000.0),
    "course_deg": (0.0, 360.0),
    "satellites": (0, 64),
}


def drop_implausible(payload: dict[str, Any]) -> None:
    """Remove every key whose value falls outside `PLAUSIBLE_RANGES`."""
    dropped = []
    for key, (lo, hi) in PLAUSIBLE_RANGES.items():
        value = payload.get(key)
        if value is not None and not lo <= value <= hi:
            dropped.append(f"{key}={value}")
            del payload[key]
    if dropped:
        log.info("refused out-of-range readings: %s", ", ".join(dropped))
