from pathlib import Path

import pytest

from weather_server.config import SensorConfig
from weather_server.sensors import FixtureSensorSource, make_source


def _write_fixtures(d: Path) -> None:
    (d / "outdoor.json").write_text(
        '[{"temperature_c": 1.0}, {"temperature_c": 2.0}, {"temperature_c": 3.0}]'
    )
    (d / "indoor.json").write_text('{"temperature_c": 22.0}')
    (d / "basement.json").write_text('{"temperature_c": 18.0, "offline": true}')


@pytest.fixture
def src(tmp_path: Path) -> FixtureSensorSource:
    _write_fixtures(tmp_path)
    return FixtureSensorSource(tmp_path)


async def test_outdoor_walks_and_loops(src: FixtureSensorSource) -> None:
    outdoor = SensorConfig(id="outdoor", role="outdoor", ip="x")
    temps = []
    for _ in range(7):
        payload = await src.poll(outdoor)
        assert payload is not None
        temps.append(payload["temperature_c"])
    assert temps == [1.0, 2.0, 3.0, 1.0, 2.0, 3.0, 1.0]


async def test_indoor_snapshot_returns_same_value(src: FixtureSensorSource) -> None:
    indoor = SensorConfig(id="indoor", role="indoor", ip="x")
    a = await src.poll(indoor)
    b = await src.poll(indoor)
    assert a == b == {"temperature_c": 22.0}


async def test_offline_flag_returns_none(src: FixtureSensorSource) -> None:
    basement = SensorConfig(id="basement", role="indoor", ip="x")
    assert await src.poll(basement) is None


async def test_missing_fixture_file_returns_none(src: FixtureSensorSource) -> None:
    ghost = SensorConfig(id="ghost", role="indoor", ip="x")
    assert await src.poll(ghost) is None


def test_all_outdoor_rows_returns_full_list(src: FixtureSensorSource) -> None:
    assert len(src.all_outdoor_rows()) == 3


def test_make_source_without_fixture_dir_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="Phase 2"):
        make_source(None)


def test_make_source_with_fixture_dir_returns_fixture_source(tmp_path: Path) -> None:
    _write_fixtures(tmp_path)
    src = make_source(str(tmp_path))
    assert isinstance(src, FixtureSensorSource)
