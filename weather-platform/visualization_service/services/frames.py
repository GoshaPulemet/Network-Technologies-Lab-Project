"""Сборка кадра карты: данные из weather_data_service -> PNG. Кадры кэшируются в памяти."""
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Dict, Hashable, List, Optional, Tuple

from clients.data_service import DataServiceClient, DataServiceError
from config import settings
from services.palettes import MODES
from services.raster import Frame, Polygon, Rendered, make_frame, render_png

MIN_GRID_POINTS = 4      # если узлов сетки меньше, добираем города


class NoDataError(Exception):
    """На выбранный момент в БД нет значений."""


def polygons_from_geojson(data: dict) -> List[Polygon]:
    """Polygon / MultiPolygon из FeatureCollection | Feature | геометрии -> [[кольца]]."""
    kind = data.get("type")
    if kind == "FeatureCollection":
        out: List[Polygon] = []
        for f in data.get("features", []):
            out.extend(polygons_from_geojson(f))
        return out
    if kind == "Feature":
        return polygons_from_geojson(data.get("geometry") or {})
    coords = data.get("coordinates", [])
    if kind == "Polygon":
        return [[[(p[0], p[1]) for p in ring] for ring in coords]]
    if kind == "MultiPolygon":
        return [[[(p[0], p[1]) for p in ring] for ring in poly] for poly in coords]
    return []


def floor_hour_utc(dt: datetime) -> datetime:
    """Любое время -> naive UTC, округлённое вниз до часа (в БД значения почасовые)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(minute=0, second=0, microsecond=0)


class TTLCache:
    def __init__(self, size: int, ttl: float):
        self._size, self._ttl = size, ttl
        self._data: "OrderedDict[Hashable, Tuple[float, object]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable):
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            stamp, value = item
            if time.monotonic() - stamp > self._ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: Hashable, value: object) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > self._size:
                self._data.popitem(last=False)


class FrameService:
    def __init__(self, client: DataServiceClient):
        self.client = client
        self._frames = TTLCache(settings.cache_size, settings.cache_ttl)
        self._static = TTLCache(8, 3600)                   # граница и города меняются редко
        self._locks: Dict[Hashable, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ---- границы и справочники ----
    def boundary_geojson(self) -> dict:
        data = self._static.get("boundary")
        if data is None:
            data = self.client.boundary()
            self._static.set("boundary", data)
        return data

    def polygons(self) -> List[Polygon]:
        polys = polygons_from_geojson(self.boundary_geojson())
        if not polys:
            raise DataServiceError("weather_data_service вернул пустую границу")
        return polys

    def frame_geometry(self) -> Frame:
        return make_frame(self.polygons(), settings.raster_width)

    def cities(self) -> List[dict]:
        data = self._static.get("cities")
        if data is None:
            data = [
                {"name": c["name"], "lat": c["latitude"], "lon": c["longitude"]}
                for c in self.client.cities()
            ]
            self._static.set("cities", data)
        return data

    # ---- кадры ----
    def _lock_for(self, key: Hashable) -> threading.Lock:
        with self._locks_guard:
            if len(self._locks) > 500:
                self._locks.clear()
            return self._locks.setdefault(key, threading.Lock())

    def _points(self, parameter: str, at: datetime) -> List[Tuple[float, float, float]]:
        snap = self.client.snapshot(parameter, at, kind="grid")
        if snap["count"] < MIN_GRID_POINTS:
            snap = self.client.snapshot(parameter, at, kind="all")
        return [(p["latitude"], p["longitude"], p["value"]) for p in snap["points"]]

    def render(self, mode_code: str, at: datetime) -> Rendered:
        mode = MODES[mode_code]
        moment = floor_hour_utc(at)
        key = (mode_code, moment)
        cached = self._frames.get(key)
        if cached is not None:
            return cached
        with self._lock_for(key):                           # одинаковые запросы не считаем дважды
            cached = self._frames.get(key)
            if cached is not None:
                return cached
            points = self._points(mode.parameter, moment)
            if not points:
                raise NoDataError(f"Нет данных на {moment.isoformat()}Z")
            rendered = render_png(points, mode, self.polygons(), self.frame_geometry())
            self._frames.set(key, rendered)
            return rendered
