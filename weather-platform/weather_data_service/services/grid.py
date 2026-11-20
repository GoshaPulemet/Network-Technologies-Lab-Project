"""Граница Республики Башкортостан и генерация сетки узлов внутри неё.

Граница берётся из GeoJSON-файла (data/rb_boundary.geojson, его скачивает
`python cli.py fetch-boundary`). Если файла нет, используется ГРУБЫЙ встроенный
контур - он нужен только чтобы сервис работал "из коробки".
"""
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import settings

Point = Tuple[float, float]      # (lon, lat)
Ring = List[Point]
Polygon = List[Ring]             # [внешнее кольцо, дыры...]

# Приблизительный контур РБ (lon, lat). Точность - десятки километров.
BUILTIN_RB_RING: Ring = [
    (53.0, 54.4), (53.3, 55.2), (53.7, 55.95), (54.2, 56.45), (55.2, 56.55),
    (56.2, 56.45), (57.0, 56.35), (57.9, 56.0), (58.5, 55.6), (58.9, 55.0),
    (59.7, 54.7), (60.1, 54.0), (60.1, 53.2), (59.8, 52.6), (59.2, 52.0),
    (58.2, 51.6), (57.0, 51.5), (56.0, 52.0), (55.3, 52.3), (54.5, 53.0),
    (53.5, 53.8),
]


# ---------- геометрия ----------
def _in_ring(lon: float, lat: float, ring: Ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def point_in_polygon(lon: float, lat: float, polygon: Polygon) -> bool:
    if not polygon or not _in_ring(lon, lat, polygon[0]):
        return False
    return not any(_in_ring(lon, lat, hole) for hole in polygon[1:])


def point_in_boundary(lon: float, lat: float, polygons: List[Polygon]) -> bool:
    return any(point_in_polygon(lon, lat, p) for p in polygons)


def bounds(polygons: List[Polygon]) -> Tuple[float, float, float, float]:
    """(lat_min, lat_max, lon_min, lon_max)"""
    pts = [pt for poly in polygons for ring in poly for pt in ring]
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return min(lats), max(lats), min(lons), max(lons)


def generate_grid(step: float, polygons: List[Polygon]) -> List[Tuple[float, float]]:
    """Узлы регулярной сетки (кратные step), попавшие внутрь границы. Возвращает (lat, lon)."""
    if step <= 0:
        raise ValueError("Шаг сетки должен быть положительным")
    lat_min, lat_max, lon_min, lon_max = bounds(polygons)
    i0, i1 = math.ceil(lat_min / step - 1e-9), math.floor(lat_max / step + 1e-9)
    j0, j1 = math.ceil(lon_min / step - 1e-9), math.floor(lon_max / step + 1e-9)
    nodes = []
    for i in range(i0, i1 + 1):
        lat = round(i * step, 4)
        for j in range(j0, j1 + 1):
            lon = round(j * step, 4)
            if point_in_boundary(lon, lat, polygons):
                nodes.append((lat, lon))
    return nodes


# ---------- загрузка GeoJSON ----------
def _polygons_from_geometry(geometry: Dict[str, Any]) -> List[Polygon]:
    kind = geometry.get("type")
    coords = geometry.get("coordinates", [])
    if kind == "Polygon":
        return [[[(p[0], p[1]) for p in ring] for ring in coords]]
    if kind == "MultiPolygon":
        return [[[(p[0], p[1]) for p in ring] for ring in poly] for poly in coords]
    if kind == "GeometryCollection":
        out: List[Polygon] = []
        for g in geometry.get("geometries", []):
            out.extend(_polygons_from_geometry(g))
        return out
    return []


def polygons_from_geojson(data: Dict[str, Any]) -> List[Polygon]:
    kind = data.get("type")
    if kind == "FeatureCollection":
        out: List[Polygon] = []
        for feature in data.get("features", []):
            out.extend(_polygons_from_geometry(feature.get("geometry") or {}))
        return out
    if kind == "Feature":
        return _polygons_from_geometry(data.get("geometry") or {})
    return _polygons_from_geometry(data)


def polygons_to_geojson(polygons: List[Polygon], name: str = "Республика Башкортостан") -> Dict[str, Any]:
    coords = [[[list(p) for p in ring] for ring in poly] for poly in polygons]
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": name},
            "geometry": {"type": "MultiPolygon", "coordinates": coords},
        }],
    }


def load_boundary(path: Optional[Path] = None) -> Tuple[List[Polygon], str]:
    """Возвращает (полигоны, источник): 'file' или 'builtin'."""
    path = Path(path) if path else settings.boundary_file
    if path.exists():
        polygons = polygons_from_geojson(json.loads(path.read_text(encoding="utf-8")))
        if polygons:
            return polygons, "file"
    return [[BUILTIN_RB_RING]], "builtin"


@lru_cache(maxsize=1)
def get_boundary() -> Tuple[Tuple[Polygon, ...], str]:
    polygons, source = load_boundary()
    return tuple(polygons), source
