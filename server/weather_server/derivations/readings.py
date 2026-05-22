"""Reading-bound derivations (the D-READING and CALIBRATED tags).

These functions are pure: given the same raw reading and calibration, they
always return the same numbers. That's the property that makes
server-side derivation the right call — bug fixes apply retroactively to
all history without backfill.
"""

from __future__ import annotations

import math
from typing import Any

from .._payload_keys import (
    K_FULL_SPECTRUM,
    K_HUMIDITY,
    K_IR,
    K_LUX,
    K_PRESSURE_PA,
    K_TEMP_C,
    K_VISIBLE,
)

HPA_PER_PA = 0.01
INHG_PER_HPA = 0.02953  # standard conversion factor

# Hypsometric (barometric) formula constants.
# P_sealevel = P_station * exp(g * h / (R_specific * T_kelvin))
G_M_S2 = 9.80665
R_SPECIFIC_DRY_AIR = 287.05  # J / (kg * K)
KELVIN_OFFSET = 273.15

# Magnus formula constants for dewpoint.
MAGNUS_B = 17.625
MAGNUS_C = 243.04


def c_to_f(celsius: float) -> float:
    return celsius * 9.0 / 5.0 + 32.0


def apply_calibration(raw_c: float, offset_c: float) -> float:
    return raw_c + offset_c


def dewpoint_c(temp_c: float, humidity_pct: float) -> float | None:
    """Magnus formula. Returns None for non-physical inputs."""
    if humidity_pct <= 0 or humidity_pct > 100:
        return None
    gamma = math.log(humidity_pct / 100.0) + (MAGNUS_B * temp_c) / (MAGNUS_C + temp_c)
    return (MAGNUS_C * gamma) / (MAGNUS_B - gamma)


def absolute_humidity_g_m3(temp_c: float, humidity_pct: float) -> float | None:
    """Absolute humidity (g/m^3) using the Clausius–Clapeyron approximation
    paired with the ideal gas law. Returns None for non-physical inputs."""
    if humidity_pct <= 0 or humidity_pct > 100:
        return None
    return (
        6.112
        * math.exp((17.67 * temp_c) / (temp_c + 243.5))
        * humidity_pct
        * 2.1674
    ) / (KELVIN_OFFSET + temp_c)


def pressure_pa_to_hpa(pa: float) -> float:
    return pa * HPA_PER_PA


def pressure_hpa_to_inhg(hpa: float) -> float:
    return hpa * INHG_PER_HPA


def pressure_station_to_sealevel_hpa(
    station_hpa: float,
    altitude_m: float,
    temp_c: float,
) -> float:
    """Hypsometric formula. Requires station temperature in Celsius and
    altitude in meters. Result is the equivalent sea-level pressure."""
    t_kelvin = temp_c + KELVIN_OFFSET
    return station_hpa * math.exp((G_M_S2 * altitude_m) / (R_SPECIFIC_DRY_AIR * t_kelvin))


def derive_reading(
    payload: dict[str, Any],
    *,
    temp_offset_c: float = 0.0,
    fallback_altitude_m: float | None = None,
) -> dict[str, Any]:
    """Compute every D-READING / CALIBRATED field from a SensorPayload.

    Missing inputs cascade to None outputs; nothing raises. Sea-level
    pressure prefers the live GPS altitude in the payload, then falls
    back to the configured altitude, then to None.
    """
    out: dict[str, Any] = {}

    raw_temp_c = payload.get(K_TEMP_C)
    raw_humidity = payload.get(K_HUMIDITY)
    raw_pressure_pa = payload.get(K_PRESSURE_PA)

    cal_temp_c: float | None = None
    if raw_temp_c is not None:
        cal_temp_c = apply_calibration(raw_temp_c, temp_offset_c)
        out["temperature_c"] = cal_temp_c
        out["temperature_f"] = c_to_f(cal_temp_c)

    if cal_temp_c is not None and raw_humidity is not None:
        dp_c = dewpoint_c(cal_temp_c, raw_humidity)
        out["dewpoint_c"] = dp_c
        out["dewpoint_f"] = c_to_f(dp_c) if dp_c is not None else None
        out["absolute_humidity_g_m3"] = absolute_humidity_g_m3(cal_temp_c, raw_humidity)

    if raw_pressure_pa is not None:
        station_hpa = pressure_pa_to_hpa(raw_pressure_pa)
        out["pressure_station_hpa"] = station_hpa
        out["pressure_station_inhg"] = pressure_hpa_to_inhg(station_hpa)

        altitude_m = payload.get("altitude_m")
        if altitude_m is None:
            altitude_m = fallback_altitude_m
        if altitude_m is not None and cal_temp_c is not None:
            sealevel_hpa = pressure_station_to_sealevel_hpa(
                station_hpa, altitude_m, cal_temp_c
            )
            out["pressure_sealevel_hpa"] = sealevel_hpa
            out["pressure_sealevel_inhg"] = pressure_hpa_to_inhg(sealevel_hpa)
        else:
            out["pressure_sealevel_hpa"] = None
            out["pressure_sealevel_inhg"] = None

    return out


def map_raw(payload: dict[str, Any]) -> dict[str, Any]:
    """Map SensorPayload field names to the API's `raw.*` block.

    The DB column is full_spectrum (avoiding the SQL reserved-word risk);
    the API field is `full`.
    """
    out: dict[str, Any] = {}
    if K_TEMP_C in payload:
        out["temperature_c"] = payload[K_TEMP_C]
    if K_HUMIDITY in payload:
        out["humidity_pct"] = payload[K_HUMIDITY]
    if K_PRESSURE_PA in payload:
        out["pressure_pa"] = payload[K_PRESSURE_PA]
    if K_LUX in payload:
        out["lux"] = payload[K_LUX]
    if K_IR in payload:
        out["ir"] = payload[K_IR]
    if K_VISIBLE in payload:
        out["visible"] = payload[K_VISIBLE]
    if K_FULL_SPECTRUM in payload:
        out["full"] = payload[K_FULL_SPECTRUM]
    return out
