"""Общие подставные данные для тестов (без сети и без weather_data_service)."""
from datetime import datetime
from typing import List

from clients.data_service import DataServiceError

# квадрат вокруг Уфы: список полигонов, полигон - список колец, точки (lon, lat)
SQUARE = [[[(54.0, 54.0), (57.0, 54.0), (57.0, 56.0), (54.0, 56.0)]]]


def square_geojson() -> dict:
    ring = [list(p) for p in SQUARE[0][0]]
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "MultiPolygon", "coordinates": [[ring + [ring[0]]]]},
    }]}


def grid_points(value_fn, step: float = 0.25) -> List[dict]:
    pts, lat = [], 54.0
    while lat <= 56.0 + 1e-9:
        lon = 54.0
        while lon <= 57.0 + 1e-9:
            pts.append({"latitude": lat, "longitude": lon, "value": value_fn(lat, lon)})
            lon += step
        lat += step
    return pts


class FakeClient:
    """Подставной DataServiceClient: считает обращения, умеет 'падать' и отдавать пусто."""

    def __init__(self, value_fn=lambda la, lo: 10.0, empty=False, fail=False, only_cities=False):
        self.value_fn, self.empty, self.fail, self.only_cities = value_fn, empty, fail, only_cities
        self.snapshot_calls: List[tuple] = []

    def snapshot(self, parameter: str, at: datetime, kind: str = "grid") -> dict:
        self.snapshot_calls.append((parameter, at, kind))
        if self.fail:
            raise DataServiceError("weather_data_service недоступен")
        if self.empty or (self.only_cities and kind == "grid"):
            return {"count": 0, "points": []}
        pts = grid_points(self.value_fn)
        return {"count": len(pts), "points": pts}

    def time_range(self) -> dict:
        if self.fail:
            raise DataServiceError("weather_data_service недоступен")
        return {"first": "2026-11-05T00:00:00Z", "last": "2026-11-08T23:00:00Z",
                "updated_at": "2026-11-06T09:00:00Z"}

    def boundary(self) -> dict:
        if self.fail:
            raise DataServiceError("weather_data_service недоступен")
        return square_geojson()

    def cities(self) -> list:
        return [{"name": "Уфа", "latitude": 54.7388, "longitude": 55.9721}]

    def close(self) -> None:
        pass
