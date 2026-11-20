"""FrameService и кэш: границы/города, LRU, ошибки, параллельные запросы."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from clients.data_service import DataServiceError
from services.frames import FrameService, NoDataError, TTLCache, polygons_from_geojson
from tests.helpers import FakeClient, square_geojson

AT = datetime(2026, 11, 6, 12, 0)


# ---------- TTLCache ----------
def test_cache_stores_and_returns_values():
    cache = TTLCache(size=2, ttl=60)
    assert cache.get("a") is None
    cache.set("a", 1)
    assert cache.get("a") == 1


def test_cache_expires_old_values():
    cache = TTLCache(size=2, ttl=-1)          # отрицательный ttl: всё уже устарело
    cache.set("a", 1)
    assert cache.get("a") is None


def test_cache_evicts_least_recently_used():
    cache = TTLCache(size=2, ttl=60)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")                            # "a" снова свежий, значит лишний - "b"
    cache.set("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1 and cache.get("c") == 3


# ---------- GeoJSON ----------
def test_polygons_from_geojson_variants():
    ring = [[0, 0], [2, 0], [2, 2], [0, 0]]
    polygon = {"type": "Polygon", "coordinates": [ring]}
    multi = {"type": "MultiPolygon", "coordinates": [[ring], [ring]]}
    assert len(polygons_from_geojson(polygon)) == 1
    assert len(polygons_from_geojson(multi)) == 2
    assert len(polygons_from_geojson({"type": "Feature", "geometry": polygon})) == 1
    assert polygons_from_geojson({"type": "Point", "coordinates": [1, 1]}) == []
    assert polygons_from_geojson({"type": "Feature", "geometry": None}) == []
    assert polygons_from_geojson({}) == []


# ---------- границы и города ----------
class CountingClient(FakeClient):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.boundary_calls = 0
        self.cities_calls = 0

    def boundary(self):
        self.boundary_calls += 1
        return super().boundary()

    def cities(self):
        self.cities_calls += 1
        return super().cities()


def test_boundary_and_cities_are_cached():
    client = CountingClient()
    svc = FrameService(client)
    svc.boundary_geojson(); svc.boundary_geojson(); svc.polygons()
    svc.cities(); svc.cities()
    assert client.boundary_calls == 1 and client.cities_calls == 1


def test_cities_are_renamed_for_the_page():
    assert FrameService(FakeClient()).cities() == [{"name": "Уфа", "lat": 54.7388, "lon": 55.9721}]


def test_empty_boundary_is_an_error():
    class EmptyBoundary(FakeClient):
        def boundary(self):
            return {"type": "FeatureCollection", "features": []}

    with pytest.raises(DataServiceError):
        FrameService(EmptyBoundary()).polygons()


def test_frame_geometry_covers_boundary():
    frame = FrameService(FakeClient()).frame_geometry()
    assert frame.lat_min < 54.0 and frame.lat_max > 56.0
    assert frame.lon_min < 54.0 and frame.lon_max > 57.0
    assert frame.width > 0 and frame.height > 0


# ---------- кадры ----------
def test_different_hours_are_cached_separately():
    client = FakeClient()
    svc = FrameService(client)
    svc.render("temperature", AT)
    svc.render("temperature", AT + timedelta(hours=1))
    assert len(client.snapshot_calls) == 2


def test_few_grid_points_trigger_city_fallback():
    class ThreePoints(FakeClient):
        def snapshot(self, parameter, at, kind="grid"):
            self.snapshot_calls.append((parameter, at, kind))
            n = 3 if kind == "grid" else 5
            pts = [{"latitude": 54.5 + i * 0.2, "longitude": 55.0 + i * 0.3, "value": 1.0} for i in range(n)]
            return {"count": n, "points": pts}

    client = ThreePoints()
    FrameService(client).render("temperature", AT)
    assert [c[2] for c in client.snapshot_calls] == ["grid", "all"]


def test_four_grid_points_are_enough():
    class FourPoints(FakeClient):
        def snapshot(self, parameter, at, kind="grid"):
            self.snapshot_calls.append((parameter, at, kind))
            pts = [{"latitude": 54.5 + i * 0.2, "longitude": 55.0 + i * 0.3, "value": 1.0} for i in range(4)]
            return {"count": 4, "points": pts}

    client = FourPoints()
    FrameService(client).render("temperature", AT)
    assert [c[2] for c in client.snapshot_calls] == ["grid"]


def test_failure_is_not_cached():
    client = FakeClient(empty=True)
    svc = FrameService(client)
    with pytest.raises(NoDataError):
        svc.render("temperature", AT)
    client.empty = False                        # данные появились
    assert svc.render("temperature", AT).png.startswith(b"\x89PNG")


def test_no_data_message_mentions_moment():
    with pytest.raises(NoDataError, match="2026-11-06T12:00:00"):
        FrameService(FakeClient(empty=True)).render("temperature", AT)


def test_parallel_identical_requests_compute_once():
    client = FakeClient()
    svc = FrameService(client)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: svc.render("temperature", AT), range(8)))
    assert len(client.snapshot_calls) == 1
    assert all(r is results[0] for r in results)
