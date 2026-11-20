"""Тесты чистой логики (без сети и БД)."""
import json

import pytest

from config import DATA_DIR
from services.grid import (
    generate_grid, load_boundary, point_in_boundary, point_in_polygon, polygons_from_geojson,
)
from services.parsing import parse_hourly, split_locations_payload


def test_builtin_boundary_contains_all_cities():
    polygons, source = load_boundary(DATA_DIR / "no_such_file.geojson")
    assert source == "builtin"
    cities = json.loads((DATA_DIR / "cities.json").read_text(encoding="utf-8"))
    outside = [c["name"] for c in cities if not point_in_boundary(c["lon"], c["lat"], polygons)]
    assert outside == []


def test_neighbour_cities_are_outside():
    polygons, _ = load_boundary(DATA_DIR / "no_such_file.geojson")
    for lon, lat in [(49.1, 55.8), (61.4, 55.16), (55.1, 51.77), (50.1, 53.2), (56.2, 58.0)]:
        assert not point_in_boundary(lon, lat, polygons)


def test_polygon_with_hole():
    square = [[(0, 0), (10, 0), (10, 10), (0, 10)], [(4, 4), (6, 4), (6, 6), (4, 6)]]
    assert point_in_polygon(1, 1, square)
    assert not point_in_polygon(5, 5, square)


def test_geojson_multipolygon_loading():
    data = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "MultiPolygon", "coordinates": [[[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]]},
    }]}
    polygons = polygons_from_geojson(data)
    assert len(polygons) == 1 and point_in_boundary(1, 1, polygons)


def test_grid_nodes_are_aligned_and_inside():
    polygons, _ = load_boundary(DATA_DIR / "no_such_file.geojson")
    nodes = generate_grid(0.25, polygons)
    assert 200 < len(nodes) < 700
    for lat, lon in nodes:
        assert round(lat / 0.25) * 0.25 == pytest.approx(lat)
        assert point_in_boundary(lon, lat, polygons)
    assert len(set(nodes)) == len(nodes)


def test_parse_hourly_converts_units():
    payload = {"hourly": {
        "time": ["2026-11-06T00:00", "2026-11-06T01:00"],
        "temperature_2m": [1.234, None],
        "snow_depth": [0.052, 0.05],           # метры -> сантиметры
        "weather_code": [71, None],
        "relative_humidity_2m": [88.4, 90],
    }}
    rows = parse_hourly(payload)
    assert rows[0]["temperature"] == 1.2
    assert rows[0]["snow_depth"] == 5.2
    assert rows[0]["weather_condition"] == "snow_light"
    assert rows[1]["temperature"] is None and rows[1]["weather_code"] is None
    assert rows[0]["pressure"] is None          # параметра нет в ответе


def test_split_payload_single_and_list_and_error():
    one = {"hourly": {"time": ["2026-11-06T00:00"]}}
    assert len(split_locations_payload(one, 1)) == 1
    assert len(split_locations_payload([one, one], 2)) == 2
    with pytest.raises(ValueError):
        split_locations_payload([one], 2)
    with pytest.raises(ValueError):
        split_locations_payload({"error": True, "reason": "bad"}, 1)
