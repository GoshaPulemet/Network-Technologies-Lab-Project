"""Чистая логика weather_data_service: коды WMO, геометрия, парсинг, сетка, настройки.
Ни сети, ни БД - самые быстрые и самые простые тесты."""
import dataclasses
import json
from datetime import datetime

import pytest

from config import DATA_DIR, Settings, _env_bool
from services.geo import haversine_km, in_rb_bbox
from services.grid import (
    bounds, generate_grid, load_boundary, point_in_boundary, point_in_polygon,
    polygons_from_geojson, polygons_to_geojson,
)
from services.parameters import PARAMETERS
from services.parsing import parse_hourly, parse_time, split_locations_payload
from services.wmo import describe_weather_code


# ---------- WMO ----------
@pytest.mark.parametrize("code, expected", [
    (0, "clear"),
    (3, "overcast"),
    (71, "snow_light"),
    (95, "thunderstorm"),
    (99, "thunderstorm_hail"),
    (None, None),
    (123, "code_123"),      # неизвестный код не должен ронять сервис
])
def test_describe_weather_code(code, expected):
    assert describe_weather_code(code) == expected


# ---------- geo ----------
def test_haversine_zero_and_symmetry():
    assert haversine_km(54.7, 55.9, 54.7, 55.9) == 0
    a = haversine_km(54.7388, 55.9721, 53.6246, 55.9502)
    b = haversine_km(53.6246, 55.9502, 54.7388, 55.9721)
    assert a == pytest.approx(b)


def test_haversine_known_distances():
    assert haversine_km(0, 0, 1, 0) == pytest.approx(111.2, rel=0.01)           # градус широты
    assert haversine_km(54.7388, 55.9721, 53.6246, 55.9502) == pytest.approx(123.9, rel=0.01)  # Уфа - Стерлитамак


@pytest.mark.parametrize("lat, lon, expected", [
    (54.7, 56.0, True),      # Уфа
    (51.3, 52.8, True),      # угол рамки включается
    (56.8, 60.4, True),
    (51.29, 56.0, False),
    (54.7, 60.41, False),
    (55.75, 37.6, False),    # Москва
])
def test_in_rb_bbox(lat, lon, expected):
    assert in_rb_bbox(lat, lon) is expected


# ---------- parameters ----------
def test_parameters_registry_is_consistent():
    assert len(PARAMETERS) == 8
    api_names = [p.api_name for p in PARAMETERS.values()]
    assert len(set(api_names)) == len(api_names)
    assert all(code == p.code for code, p in PARAMETERS.items())
    assert PARAMETERS["snow_depth"].factor == 100      # метры -> сантиметры
    assert PARAMETERS["pressure"].unit == "гПа"        # визуализация переводит именно из гПа


# ---------- parsing ----------
def test_parse_time_accepts_z_and_offsets():
    assert parse_time("2026-11-06T12:00") == datetime(2026, 11, 6, 12)
    assert parse_time("2026-11-06T12:00Z") == datetime(2026, 11, 6, 12)
    assert parse_time("2026-11-06T17:00+05:00") == datetime(2026, 11, 6, 12)


def test_parse_hourly_requires_time_block():
    with pytest.raises(ValueError):
        parse_hourly({})
    with pytest.raises(ValueError):
        parse_hourly({"hourly": {"time": []}})


def test_parse_hourly_tolerates_short_and_broken_series():
    payload = {"hourly": {
        "time": ["2026-11-06T00:00", "2026-11-06T01:00", "2026-11-06T02:00"],
        "temperature_2m": [1.0, "abc"],      # короче времени и с мусором
        "weather_code": [0.0],
    }}
    rows = parse_hourly(payload)
    assert [r["temperature"] for r in rows] == [1.0, None, None]
    assert rows[0]["weather_code"] == 0 and rows[0]["weather_condition"] == "clear"   # 0 - не "пусто"
    assert rows[1]["weather_code"] is None


def test_parse_hourly_rounds_per_parameter():
    payload = {"hourly": {
        "time": ["2026-11-06T00:00"],
        "precipitation": [0.456], "relative_humidity_2m": [88.6], "pressure_msl": [1008.26],
    }}
    row = parse_hourly(payload)[0]
    assert row["precipitation"] == 0.46      # 2 знака
    assert row["humidity"] == 89             # 0 знаков
    assert row["pressure"] == 1008.3         # 1 знак


def test_split_payload_rejects_garbage_and_uses_default_reason():
    with pytest.raises(ValueError):
        split_locations_payload("oops", 1)
    with pytest.raises(ValueError, match="ошибку"):
        split_locations_payload({"error": True}, 1)
    ok = {"hourly": {"time": ["2026-11-06T00:00"]}}
    assert split_locations_payload({"error": False, **ok}, 1) == [{"error": False, **ok}]


# ---------- grid ----------
def test_generate_grid_rejects_bad_step():
    square = [[[(0, 0), (1, 0), (1, 1), (0, 1)]]]
    for step in (0, -0.25):
        with pytest.raises(ValueError):
            generate_grid(step, square)


def test_generate_grid_small_square_has_exact_nodes():
    square = [[[(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]]]
    nodes = generate_grid(0.25, square)
    assert len(nodes) == 9
    assert {lat for lat, _ in nodes} == {0.25, 0.5, 0.75}
    assert {lon for _, lon in nodes} == {0.25, 0.5, 0.75}


def test_bounds_and_empty_polygon():
    polys = [[[(1, 10), (3, 10), (3, 12), (1, 12)]]]
    assert bounds(polys) == (10, 12, 1, 3)          # lat_min, lat_max, lon_min, lon_max
    assert point_in_polygon(2, 11, []) is False


def test_geojson_variants():
    ring = [[0, 0], [2, 0], [2, 2], [0, 0]]
    polygon = {"type": "Polygon", "coordinates": [ring]}
    expected = [[[(0, 0), (2, 0), (2, 2), (0, 0)]]]
    assert polygons_from_geojson(polygon) == expected
    assert polygons_from_geojson({"type": "Feature", "geometry": polygon}) == expected
    assert polygons_from_geojson({"type": "GeometryCollection", "geometries": [polygon, polygon]}) == expected * 2
    assert polygons_from_geojson({"type": "Point", "coordinates": [1, 1]}) == []
    assert polygons_from_geojson({"type": "Feature", "geometry": None}) == []


def test_geojson_roundtrip():
    polys = [[[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 0.0)]]]
    assert polygons_from_geojson(polygons_to_geojson(polys)) == polys


def test_load_boundary_falls_back_to_builtin(tmp_path):
    empty = tmp_path / "empty.geojson"
    empty.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    _, source = load_boundary(empty)
    assert source == "builtin"


def test_real_boundary_file_contains_every_city():
    """Защита от опечатки в координатах cities.json."""
    polygons, source = load_boundary()
    assert source == "file"
    cities = json.loads((DATA_DIR / "cities.json").read_text(encoding="utf-8"))
    outside = [c["name"] for c in cities if not point_in_boundary(c["lon"], c["lat"], polygons)]
    assert outside == []
    assert not point_in_boundary(37.6, 55.75, polygons)     # Москва


# ---------- config ----------
@pytest.mark.parametrize("raw, expected", [
    ("1", True), ("true", True), ("TRUE", True), (" yes ", True), ("on", True),
    ("0", False), ("false", False), ("no", False), ("off", False), ("", False), ("мусор", False),
])
def test_env_bool_values(monkeypatch, raw, expected):
    monkeypatch.setenv("TEST_FLAG", raw)
    assert _env_bool("TEST_FLAG", True) is expected


def test_env_bool_default_when_unset(monkeypatch):
    monkeypatch.delenv("TEST_FLAG", raising=False)
    assert _env_bool("TEST_FLAG", True) is True
    assert _env_bool("TEST_FLAG", False) is False


ENV_NAMES = ["DATABASE_URL", "AUTO_SEED", "AUTO_SYNC", "GRID_STEP", "CORS_ORIGINS", "FORECAST_DAYS"]


def test_settings_defaults(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    s = Settings.from_env()
    assert s.database_url.startswith("sqlite:///") and s.database_url.endswith("weather_data.db")
    assert (s.auto_seed, s.auto_sync, s.grid_step, s.forecast_days) == (True, False, 0.25, 3)
    assert s.cors_origins == ["*"]


def test_settings_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:////data/weather_data.db")
    monkeypatch.setenv("AUTO_SYNC", "yes")
    monkeypatch.setenv("GRID_STEP", "0.5")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.com, http://b.com ,")
    s = Settings.from_env()
    assert s.database_url == "sqlite:////data/weather_data.db"
    assert s.auto_sync is True and s.grid_step == 0.5
    assert s.cors_origins == ["http://a.com", "http://b.com"]


def test_settings_are_frozen():
    s = Settings.from_env()
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.grid_step = 1.0
