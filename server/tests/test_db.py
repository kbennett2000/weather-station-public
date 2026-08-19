from pathlib import Path

import pytest

from weather_server import db


@pytest.fixture
def conn(tmp_path: Path):
    c = db.init_db(tmp_path / "test.db")
    yield c
    c.close()


def test_init_creates_schema_and_sets_version(tmp_path: Path) -> None:
    c = db.init_db(tmp_path / "fresh.db")
    version = c.execute("PRAGMA user_version").fetchone()[0]
    assert version == db.SCHEMA_VERSION
    journal = c.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal == "wal"
    c.close()


def test_init_is_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "idem.db"
    db.init_db(p).close()
    c2 = db.init_db(p)
    assert c2.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    c2.close()


def test_insert_and_latest_round_trip(conn) -> None:
    payload = {
        "temperature_c": 18.4,
        "humidity_pct": 42.1,
        "pressure_pa": 80443,
        "lux": 12450.0,
        "ir": 230,
        "visible": 8200,
        "full_spectrum": 8430,
        "latitude": 39.7392,
        "longitude": -104.9903,
        "altitude_m": 1609.3,
        "satellites": 9,
        "speed_kmh": 0.0,
        "course_deg": 0.0,
        "rssi_dbm": -62,
        "uptime_s": 84320,
        "free_heap_bytes": 178432,
    }
    rowid = db.insert_outdoor_reading(conn, timestamp=1716393000, payload=payload)
    assert rowid > 0

    row = db.latest_outdoor_reading(conn)
    assert row is not None
    assert row["timestamp"] == 1716393000
    assert row["temperature_c"] == pytest.approx(18.4)
    assert row["full_spectrum"] == 8430
    assert row["altitude_m"] == pytest.approx(1609.3)


def test_latest_returns_none_on_empty_table(conn) -> None:
    assert db.latest_outdoor_reading(conn) is None
    assert db.latest_outdoor_timestamp(conn) is None


def test_range_query_orders_ascending(conn) -> None:
    for ts in (1000, 3000, 2000):
        db.insert_outdoor_reading(conn, timestamp=ts, payload={"temperature_c": float(ts)})
    rows = db.outdoor_readings_in_range(conn, 1500, 3500)
    assert [r["timestamp"] for r in rows] == [2000, 3000]


def test_partial_payload_stores_nulls(conn) -> None:
    db.insert_outdoor_reading(
        conn,
        timestamp=2000,
        payload={"temperature_c": 20.0, "humidity_pct": 50.0},
    )
    row = db.latest_outdoor_reading(conn)
    assert row is not None
    assert row["temperature_c"] == pytest.approx(20.0)
    assert row["pressure_pa"] is None
    assert row["latitude"] is None
    assert row["rssi_dbm"] is None


def test_db_ok(conn) -> None:
    assert db.db_ok(conn) is True


# ── external_readings + the v1 -> v2 migration ─────────────────────────────

# A frozen copy of the schema as it shipped at SCHEMA_VERSION = 1. Kept
# here rather than imported from db.py on purpose: it is a historical
# fixture, and it must NOT track future edits to the live schema.
_V1_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS outdoor_readings (
    id                  INTEGER PRIMARY KEY,
    timestamp           INTEGER NOT NULL,
    temperature_c       REAL,
    humidity_pct        REAL,
    pressure_pa         REAL,
    lux                 REAL,
    ir                  INTEGER,
    visible             INTEGER,
    full_spectrum       INTEGER,
    latitude            REAL,
    longitude           REAL,
    altitude_m          REAL,
    satellites          INTEGER,
    speed_kmh           REAL,
    course_deg          REAL,
    rssi_dbm            INTEGER,
    uptime_s            INTEGER,
    free_heap_bytes     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_outdoor_readings_timestamp
    ON outdoor_readings (timestamp);
"""


def _make_v1_db(path: Path, rows: int = 3) -> None:
    """Build a genuine schema-v1 file with outdoor data in it."""
    import sqlite3

    c = sqlite3.connect(str(path), isolation_level=None)
    c.executescript(_V1_SCHEMA_SQL)
    for i in range(rows):
        c.execute(
            "INSERT INTO outdoor_readings (timestamp, temperature_c, pressure_pa) "
            "VALUES (?, ?, ?)",
            (1_700_000_000 + i * 60, 18.0 + i, 84725.0),
        )
    c.execute("PRAGMA user_version = 1")
    c.close()


def test_init_creates_external_readings_table(conn) -> None:
    names = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "external_readings" in names
    assert "outdoor_readings" in names


def test_migrate_v1_to_v2_preserves_outdoor_rows(tmp_path: Path) -> None:
    p = tmp_path / "legacy.db"
    _make_v1_db(p, rows=5)

    c = db.init_db(p)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 2
    # Every original row survives, unchanged.
    rows = c.execute("SELECT timestamp, temperature_c FROM outdoor_readings ORDER BY id").fetchall()
    assert len(rows) == 5
    assert [r[1] for r in rows] == [18.0, 19.0, 20.0, 21.0, 22.0]
    assert c.execute("SELECT COUNT(*) FROM external_readings").fetchone()[0] == 0
    c.close()


def test_migration_is_idempotent_on_reopen(tmp_path: Path) -> None:
    p = tmp_path / "legacy2.db"
    _make_v1_db(p, rows=2)
    db.init_db(p).close()
    c = db.init_db(p)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 2
    assert c.execute("SELECT COUNT(*) FROM outdoor_readings").fetchone()[0] == 2
    c.close()


def test_init_rejects_newer_schema_version(tmp_path: Path) -> None:
    # Downgrading the code without restoring the DB file must fail loudly
    # rather than silently operating on a schema it does not understand.
    p = tmp_path / "future.db"
    db.init_db(p).close()
    import sqlite3

    c = sqlite3.connect(str(p), isolation_level=None)
    c.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    c.close()
    with pytest.raises(RuntimeError, match="Downgrade is not supported"):
        db.init_db(p)


_OBS = {
    "observed_at": 1_700_000_000,
    "provider": "open-meteo",
    "source": "open-meteo model point",
    "station_id": None,
    "distance_km": 2.4,
    "wind_speed_ms": 3.1,
    "wind_gust_ms": 5.4,
    "wind_direction_deg": 212.0,
    "cloud_cover_pct": 40.0,
    "uv_index": 5.0,
    "precip_mm": 0.0,
    "visibility_m": 24000.0,
    "confidence": "normal",
}


def test_insert_external_reading_round_trip(conn) -> None:
    assert db.insert_external_reading(conn, 1_700_000_000, _OBS) is True
    row = db.latest_external_reading(conn)
    assert row is not None
    assert row["provider"] == "open-meteo"
    assert row["wind_speed_ms"] == 3.1
    assert row["wind_direction_deg"] == 212.0
    assert row["timestamp"] == 1_700_000_000


def test_insert_external_reading_dedups_same_provider_and_timestamp(conn) -> None:
    assert db.insert_external_reading(conn, 1_700_000_000, _OBS) is True
    assert db.insert_external_reading(conn, 1_700_000_000, _OBS) is False
    assert conn.execute("SELECT COUNT(*) FROM external_readings").fetchone()[0] == 1


def test_insert_external_reading_allows_different_provider_same_timestamp(conn) -> None:
    db.insert_external_reading(conn, 1_700_000_000, _OBS)
    other = {**_OBS, "provider": "nws"}
    assert db.insert_external_reading(conn, 1_700_000_000, other) is True
    assert conn.execute("SELECT COUNT(*) FROM external_readings").fetchone()[0] == 2


def test_insert_external_reading_stores_nulls_for_missing_fields(conn) -> None:
    db.insert_external_reading(conn, 42, {"provider": "nws"})
    row = db.latest_external_reading(conn)
    assert row is not None
    assert row["wind_speed_ms"] is None
    assert row["uv_index"] is None


def test_external_readings_in_range_orders_ascending(conn) -> None:
    for i in (3, 1, 2):
        db.insert_external_reading(conn, 1_700_000_000 + i * 3600, {**_OBS, "observed_at": i})
    rows = db.external_readings_in_range(conn, 0, 2_000_000_000)
    assert [r["timestamp"] for r in rows] == [
        1_700_000_000 + 3600,
        1_700_000_000 + 7200,
        1_700_000_000 + 10800,
    ]


def test_external_readings_in_range_excludes_outside_window(conn) -> None:
    db.insert_external_reading(conn, 1000, _OBS)
    db.insert_external_reading(conn, 5000, {**_OBS, "provider": "nws"})
    rows = db.external_readings_in_range(conn, 2000, 6000)
    assert [r["timestamp"] for r in rows] == [5000]


def test_latest_external_reading_none_when_empty(conn) -> None:
    assert db.latest_external_reading(conn) is None
