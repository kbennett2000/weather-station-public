from datetime import datetime, timezone

import pytest

from weather_server.derivations import astronomy


DENVER_LAT = 39.7392
DENVER_LON = -104.9903


@pytest.fixture
def summer_noon_utc() -> datetime:
    # 2026-06-21 19:00 UTC ≈ 13:00 Mountain Daylight (solar noon-ish in Denver)
    return datetime(2026, 6, 21, 19, 0, 0, tzinfo=timezone.utc)


def test_sun_position_high_at_summer_noon(summer_noon_utc: datetime) -> None:
    pos = astronomy.sun_position(summer_noon_utc, DENVER_LAT, DENVER_LON)
    assert pos.altitude_deg > 65  # near solstice the sun is very high


def test_sun_position_below_horizon_at_midnight() -> None:
    midnight = datetime(2026, 6, 22, 7, 0, 0, tzinfo=timezone.utc)  # 1 AM local
    pos = astronomy.sun_position(midnight, DENVER_LAT, DENVER_LON)
    assert pos.altitude_deg < 0


def test_sun_times_produces_sunrise_before_sunset(summer_noon_utc: datetime) -> None:
    times = astronomy.sun_times(summer_noon_utc, DENVER_LAT, DENVER_LON)
    assert times.sunrise is not None and times.sunset is not None
    assert times.sunrise < times.sunset
    assert times.dawn is not None and times.dawn < times.sunrise


def test_solar_noon_within_minutes_of_local_noon(summer_noon_utc: datetime) -> None:
    times = astronomy.sun_times(summer_noon_utc, DENVER_LAT, DENVER_LON)
    # Solar noon in Denver in summer is ~1 PM local = ~19:00 UTC.
    delta_minutes = abs((times.solar_noon - summer_noon_utc).total_seconds()) / 60
    assert delta_minutes < 60


def test_moon_position_returns_finite_numbers(summer_noon_utc: datetime) -> None:
    pos = astronomy.moon_position(summer_noon_utc, DENVER_LAT, DENVER_LON)
    assert -90 <= pos.altitude_deg <= 90
    assert 0 <= pos.azimuth_deg <= 360
    assert 350_000 < pos.distance_km < 410_000


def test_moon_illumination_in_unit_range(summer_noon_utc: datetime) -> None:
    illum = astronomy.moon_illumination(summer_noon_utc)
    assert 0.0 <= illum.fraction <= 1.0
    assert 0.0 <= illum.phase <= 1.0


def test_moon_phase_name_for_known_full_phase() -> None:
    assert astronomy.moon_phase_name(0.5) == "Full Moon"
    assert astronomy.moon_phase_name(0.0) == "New Moon"
    assert astronomy.moon_phase_name(0.25) == "First Quarter"
    assert astronomy.moon_phase_name(0.75) == "Last Quarter"


def test_moon_phase_icon_for_full() -> None:
    assert astronomy.moon_phase_icon(0.5) == "🌕"
    assert astronomy.moon_phase_icon(0.0) == "🌑"


def test_moon_times_returns_expected_keys(summer_noon_utc: datetime) -> None:
    result = astronomy.moon_times(summer_noon_utc, DENVER_LAT, DENVER_LON)
    assert set(result.keys()) == {"rise", "set", "always_up", "always_down"}


def test_resolve_timezone_for_denver_returns_iana_name() -> None:
    tz = astronomy.resolve_timezone(DENVER_LAT, DENVER_LON)
    assert tz == "America/Denver"


def test_resolve_timezone_falls_back_to_utc_when_coords_none() -> None:
    assert astronomy.resolve_timezone(None, None) == "UTC"


def test_to_local_projects_into_zone(summer_noon_utc: datetime) -> None:
    local = astronomy.to_local(summer_noon_utc, "America/Denver")
    # Summer in Denver = UTC-6 (MDT)
    assert local.utcoffset() is not None
    assert local.utcoffset().total_seconds() == -6 * 3600  # type: ignore[union-attr]
