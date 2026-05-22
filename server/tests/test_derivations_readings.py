"""Reading-bound derivations.

Includes the pressure-quadruple test from CLAUDE.md done criteria,
plus the additional Denver test case using realistic station pressure
that does produce sealevel ≈1023 hPa with the hypsometric formula.
"""

import math

import pytest

from weather_server.derivations import readings


def test_c_to_f_known_points() -> None:
    assert readings.c_to_f(0) == pytest.approx(32.0)
    assert readings.c_to_f(100) == pytest.approx(212.0)
    assert readings.c_to_f(-40) == pytest.approx(-40.0)


def test_apply_calibration_adds_offset() -> None:
    assert readings.apply_calibration(18.9, -0.5) == pytest.approx(18.4)


def test_dewpoint_magnus_round_numbers() -> None:
    # At 100% RH, dewpoint == air temperature.
    assert readings.dewpoint_c(20.0, 100.0) == pytest.approx(20.0, abs=0.01)
    # Sanity: dewpoint < air temp when RH < 100%.
    dp = readings.dewpoint_c(20.0, 50.0)
    assert dp is not None and dp < 20.0


def test_dewpoint_invalid_humidity_returns_none() -> None:
    assert readings.dewpoint_c(20.0, 0.0) is None
    assert readings.dewpoint_c(20.0, 101.0) is None


def test_absolute_humidity_positive_for_normal_air() -> None:
    ah = readings.absolute_humidity_g_m3(20.0, 50.0)
    assert ah is not None and 8.0 < ah < 10.0


def test_pressure_pa_to_hpa() -> None:
    assert readings.pressure_pa_to_hpa(80443) == pytest.approx(804.43)


def test_pressure_hpa_to_inhg_doc_example() -> None:
    assert readings.pressure_hpa_to_inhg(804.43) == pytest.approx(23.75, abs=0.005)


def test_pressure_station_to_sealevel_formula() -> None:
    # Hypsometric formula consistency check.
    station = 1013.25
    altitude = 0.0
    temp = 15.0
    assert readings.pressure_station_to_sealevel_hpa(station, altitude, temp) == pytest.approx(
        1013.25
    )


def test_pressure_quadruple_matches_doc_example() -> None:
    """The example in 02-api-design.md uses raw.pressure_pa = 84725 with
    altitude_m = 1609.3 and calibrated temp = 18.4°C, producing
    station 847.25 hPa / 25.02 inHg and sealevel 1023.0 hPa / 30.21 inHg.
    This test is the doc-conformance check: if the spec example changes,
    this should change with it."""
    derived = readings.derive_reading(
        {
            "temperature_c": 18.9,
            "humidity_pct": 42.1,
            "pressure_pa": 84725,
            "altitude_m": 1609.3,
        },
        temp_offset_c=-0.5,
        fallback_altitude_m=1609.3,
    )
    assert derived["pressure_station_hpa"] == pytest.approx(847.25)
    assert derived["pressure_station_inhg"] == pytest.approx(25.02, abs=0.01)
    assert derived["pressure_sealevel_hpa"] == pytest.approx(1023.0, abs=1.0)
    assert derived["pressure_sealevel_inhg"] == pytest.approx(30.21, abs=0.05)


def test_pressure_quadruple_hypsometric_formula_check() -> None:
    """Independent math check on the hypsometric formula, using a
    different station pressure than the doc example. Pins the formula's
    output to ~971 hPa / 28.69 inHg for pressure_pa=80443 at Denver
    elevation. Not a doc test — pure math correctness."""
    derived = readings.derive_reading(
        {
            "temperature_c": 18.4,
            "humidity_pct": 42.0,
            "pressure_pa": 80443,
            "altitude_m": 1609.3,
        },
        temp_offset_c=0.0,
    )
    assert derived["pressure_station_hpa"] == pytest.approx(804.43)
    assert derived["pressure_station_inhg"] == pytest.approx(23.75, abs=0.01)
    assert derived["pressure_sealevel_hpa"] == pytest.approx(971.4, abs=1.0)
    assert derived["pressure_sealevel_inhg"] == pytest.approx(28.69, abs=0.05)


def test_pressure_sealevel_falls_back_to_configured_altitude() -> None:
    derived = readings.derive_reading(
        {"temperature_c": 22.0, "humidity_pct": 40.0, "pressure_pa": 80520},
        fallback_altitude_m=1609.3,
    )
    assert derived["pressure_sealevel_hpa"] is not None


def test_pressure_sealevel_none_when_no_altitude_anywhere() -> None:
    derived = readings.derive_reading(
        {"temperature_c": 22.0, "humidity_pct": 40.0, "pressure_pa": 80520},
    )
    assert derived["pressure_sealevel_hpa"] is None
    assert derived["pressure_sealevel_inhg"] is None
    assert derived["pressure_station_hpa"] is not None


def test_calibration_offset_propagates_to_derived_temp() -> None:
    derived = readings.derive_reading(
        {"temperature_c": 20.0, "humidity_pct": 50.0},
        temp_offset_c=-0.5,
    )
    assert derived["temperature_c"] == pytest.approx(19.5)
    assert derived["temperature_f"] == pytest.approx(readings.c_to_f(19.5))


def test_missing_inputs_skip_outputs() -> None:
    derived = readings.derive_reading({})
    assert derived == {}


def test_map_raw_maps_full_spectrum_to_full() -> None:
    raw = readings.map_raw(
        {
            "temperature_c": 18.4,
            "humidity_pct": 42.1,
            "pressure_pa": 80443,
            "lux": 12450.0,
            "ir": 230,
            "visible": 8200,
            "full_spectrum": 8430,
        }
    )
    assert raw["full"] == 8430
    assert "full_spectrum" not in raw
    assert raw["lux"] == 12450.0
    assert math.isclose(raw["pressure_pa"], 80443)
