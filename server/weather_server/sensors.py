"""Sensor poll abstraction.

A SensorSource returns a SensorPayload dict (the same shape the fixture
files use, the same shape the DB inserts) for a configured sensor. Two
implementations exist:

- FixtureSensorSource: reads JSON files from a directory; the outdoor
  file is a list walked round-robin; indoor/basement are single
  snapshots that may carry an `offline: true` flag.
- (Phase 2) HttpSensorSource: real HTTP polling of ESP32 /data endpoints.
  Not implemented in Phase 1.

A payload of None means "the sensor is unreachable / offline right now".
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Protocol

from .config import SensorConfig

log = logging.getLogger(__name__)

SensorPayload = dict[str, Any]


class SensorSource(Protocol):
    async def poll(self, sensor: SensorConfig) -> SensorPayload | None: ...
    def all_outdoor_rows(self) -> list[SensorPayload]: ...


class FixtureSensorSource:
    """Reads SensorPayloads from JSON files under `fixture_dir`.

    File layout:
        fixtures/
          outdoor.json   # list of payloads, walked round-robin
          indoor.json    # single payload object (optional `offline: true`)
          basement.json  # single payload object (optional `offline: true`)
    """

    def __init__(self, fixture_dir: Path | str) -> None:
        self.fixture_dir = Path(fixture_dir)
        self._outdoor_rows: list[SensorPayload] | None = None
        self._cursor = 0
        self._snapshots: dict[str, SensorPayload | None] = {}
        self._lock = asyncio.Lock()
        log.info("fixture source rooted at %s", self.fixture_dir)

    async def poll(self, sensor: SensorConfig) -> SensorPayload | None:
        async with self._lock:
            if sensor.role == "outdoor":
                return self._next_outdoor()
            return self._load_snapshot(sensor.id)

    def all_outdoor_rows(self) -> list[SensorPayload]:
        """Used by the logger task at startup to prefill the DB."""
        return list(self._load_outdoor())

    def _load_outdoor(self) -> list[SensorPayload]:
        if self._outdoor_rows is None:
            path = self.fixture_dir / "outdoor.json"
            with path.open() as f:
                data = json.load(f)
            if not isinstance(data, list) or not data:
                raise ValueError(f"{path}: expected a non-empty JSON array")
            self._outdoor_rows = data
        return self._outdoor_rows

    def _next_outdoor(self) -> SensorPayload | None:
        rows = self._load_outdoor()
        row = rows[self._cursor % len(rows)]
        self._cursor += 1
        if row.get("offline"):
            return None
        return {k: v for k, v in row.items() if k != "offline"}

    def _load_snapshot(self, sensor_id: str) -> SensorPayload | None:
        if sensor_id not in self._snapshots:
            path = self.fixture_dir / f"{sensor_id}.json"
            if not path.exists():
                self._snapshots[sensor_id] = None
            else:
                with path.open() as f:
                    data = json.load(f)
                self._snapshots[sensor_id] = data
        snap = self._snapshots[sensor_id]
        if snap is None or snap.get("offline"):
            return None
        return {k: v for k, v in snap.items() if k != "offline"}


def make_source(fixture_dir: str | None) -> SensorSource:
    """Pick a SensorSource based on config.

    Phase 1: only fixture mode. Phase 2 will return HttpSensorSource when
    fixture_dir is None.
    """
    if fixture_dir is None:
        raise NotImplementedError(
            "Real HTTP polling is Phase 2. Set [development] fixture_dir in weather.toml."
        )
    return FixtureSensorSource(fixture_dir)
