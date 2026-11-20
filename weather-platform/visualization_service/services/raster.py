"""Построение растрового слоя погоды.

Вход - значения в узлах (lat, lon, value), выход - PNG с прозрачностью, обрезанный по границе РБ.
Картинка строится сразу в проекции Web Mercator (как подложка карты), поэтому в браузере
её достаточно положить на карту по четырём углам, без перепроецирования.

Алгоритм:
  1. значения в узлах -> гладкое поле (ядерная регрессия Надарая-Уотсона с гауссовым ядром);
     считаем на уменьшенной сетке, потом растягиваем бикубически - это быстро и без "бычьих глаз"
     вокруг узлов, которые даёт обратное взвешивание расстояний;
  2. поле -> цвет и прозрачность по палитре режима;
  3. всё за пределами границы РБ делаем прозрачным (с антиалиасингом по краю).
"""
import io
import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw

from services.palettes import Mode, hex_to_rgb

Polygon = List[List[Tuple[float, float]]]    # [внешнее кольцо, дыры...], точки (lon, lat)
Point = Tuple[float, float, float]           # (lat, lon, value)

KM_PER_DEG_LAT = 110.57
KM_PER_DEG_LON_EQ = 111.32
COARSE = 4          # во сколько раз расчётная сетка грубее итоговой картинки
MASK_SS = 2         # суперсэмплинг маски границы (сглаживание края)


# ---------- проекция ----------
def merc_y(lat_deg: float) -> float:
    """Нормализованная меркаторская координата (радианы)."""
    return math.log(math.tan(math.pi / 4 + math.radians(lat_deg) / 2))


def inv_merc_y(y):
    return np.degrees(2 * np.arctan(np.exp(y)) - math.pi / 2)


@dataclass(frozen=True)
class Frame:
    """Прямоугольник слоя в градусах и размер картинки в пикселях."""
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    width: int
    height: int

    @property
    def y_top(self) -> float:
        return merc_y(self.lat_max)

    @property
    def y_bottom(self) -> float:
        return merc_y(self.lat_min)

    def to_pixels(self, lon: float, lat: float) -> Tuple[float, float]:
        x = (lon - self.lon_min) / (self.lon_max - self.lon_min) * self.width
        y = (self.y_top - merc_y(lat)) / (self.y_top - self.y_bottom) * self.height
        return x, y


def polygons_bounds(polygons: Sequence[Polygon], pad: float = 0.05) -> Tuple[float, float, float, float]:
    """(lat_min, lat_max, lon_min, lon_max) по всем вершинам границы + небольшой запас."""
    pts = [p for poly in polygons for ring in poly for p in ring]
    if not pts:
        raise ValueError("Пустая граница")
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return min(lats) - pad, max(lats) + pad, min(lons) - pad, max(lons) + pad


def make_frame(polygons: Sequence[Polygon], width: int) -> Frame:
    lat_min, lat_max, lon_min, lon_max = polygons_bounds(polygons)
    dx = math.radians(lon_max - lon_min)
    dy = merc_y(lat_max) - merc_y(lat_min)
    height = max(2, round(width * dy / dx))
    return Frame(lat_min, lat_max, lon_min, lon_max, width, height)


# ---------- интерполяция ----------
def estimate_sigma_km(lats: np.ndarray, lons: np.ndarray, lat_mid: float) -> float:
    """Ширина ядра: чуть меньше среднего расстояния до 4 ближайших соседей.
    Для сетки 0.25° это ~20 км; для редких точек (только города) - больше."""
    n = len(lats)
    if n < 2:
        return 50.0
    kx = KM_PER_DEG_LON_EQ * math.cos(math.radians(lat_mid))
    x = lons * kx
    y = lats * KM_PER_DEG_LAT
    d = np.sqrt((x[:, None] - x[None, :]) ** 2 + (y[:, None] - y[None, :]) ** 2)
    np.fill_diagonal(d, np.inf)
    k = min(4, n - 1)
    nearest = np.sort(d, axis=1)[:, :k]
    return float(max(10.0, 0.9 * np.mean(nearest)))


def smooth_field(lats, lons, values, q_lat, q_lon, sigma_km, lat_mid, chunk=6000) -> np.ndarray:
    """Значение в точках запроса (q_lat, q_lon - плоские массивы)."""
    kx = KM_PER_DEG_LON_EQ * math.cos(math.radians(lat_mid))
    px, py = lons * kx, lats * KM_PER_DEG_LAT
    qx, qy = q_lon * kx, q_lat * KM_PER_DEG_LAT
    inv = 1.0 / (2.0 * sigma_km ** 2)
    out = np.empty(len(qx), dtype=np.float64)
    for start in range(0, len(qx), chunk):
        sl = slice(start, start + chunk)
        d2 = (qx[sl, None] - px[None, :]) ** 2 + (qy[sl, None] - py[None, :]) ** 2
        # вычитаем минимум: отношение не меняется, зато нет деления 0/0 далеко от узлов
        w = np.exp(-(d2 - d2.min(axis=1, keepdims=True)) * inv)
        out[sl] = (w @ values) / w.sum(axis=1)
    return out


def build_field(points: Sequence[Point], frame: Frame) -> np.ndarray:
    """Гладкое поле размера (height, width) в единицах значений."""
    arr = np.asarray(points, dtype=np.float64)
    lats, lons, vals = arr[:, 0], arr[:, 1], arr[:, 2]
    lat_mid = (frame.lat_min + frame.lat_max) / 2
    sigma = estimate_sigma_km(lats, lons, lat_mid)

    cw = max(2, math.ceil(frame.width / COARSE))
    ch = max(2, math.ceil(frame.height / COARSE))
    # центры ячеек грубой сетки в координатах итоговой картинки
    xs = (np.arange(cw) + 0.5) * (frame.width / cw)
    ys = (np.arange(ch) + 0.5) * (frame.height / ch)
    lon_axis = frame.lon_min + xs / frame.width * (frame.lon_max - frame.lon_min)
    merc = frame.y_top - ys / frame.height * (frame.y_top - frame.y_bottom)
    lat_axis = inv_merc_y(merc)
    q_lon, q_lat = np.meshgrid(lon_axis, lat_axis)

    coarse = smooth_field(lats, lons, vals, q_lat.ravel(), q_lon.ravel(), sigma, lat_mid)
    coarse = coarse.reshape(ch, cw).astype(np.float32)
    img = Image.fromarray(coarse, mode="F").resize((frame.width, frame.height), Image.BICUBIC)
    return np.asarray(img, dtype=np.float64)


# ---------- маска границы ----------
def boundary_mask(polygons: Sequence[Polygon], frame: Frame) -> np.ndarray:
    """Маска 0..1 размера (height, width): 1 внутри РБ, на краю - плавный переход."""
    ss = MASK_SS
    img = Image.new("L", (frame.width * ss, frame.height * ss), 0)
    draw = ImageDraw.Draw(img)
    for poly in polygons:
        for i, ring in enumerate(poly):
            xy = [tuple(c * ss for c in frame.to_pixels(lon, lat)) for lon, lat in ring]
            if len(xy) >= 3:
                draw.polygon(xy, fill=255 if i == 0 else 0)
    img = img.resize((frame.width, frame.height), Image.LANCZOS)
    return np.asarray(img, dtype=np.float64) / 255.0


# ---------- цвет ----------
def colorize(values: np.ndarray, mode: Mode) -> np.ndarray:
    """values - в единицах отображения. Возвращает RGBA float (0..255) без учёта маски."""
    xs = np.array([s[0] for s in mode.stops], dtype=np.float64)
    rgb = np.array([hex_to_rgb(s[1]) for s in mode.stops], dtype=np.float64)
    alpha = np.array([s[2] for s in mode.stops], dtype=np.float64)
    v = np.clip(values, xs[0], xs[-1])
    out = np.empty(values.shape + (4,), dtype=np.float64)
    for c in range(3):
        out[..., c] = np.interp(v, xs, rgb[:, c])
    out[..., 3] = np.interp(v, xs, alpha) * 255.0
    return out


@dataclass
class Rendered:
    png: bytes
    vmin: float
    vmax: float


def render_png(points: Sequence[Point], mode: Mode, polygons: Sequence[Polygon], frame: Frame) -> Rendered:
    """points - (lat, lon, значение в единицах БД)."""
    if len(points) == 0:
        raise ValueError("Нет точек для построения слоя")
    shown = [(la, lo, v * mode.factor) for la, lo, v in points]
    field = build_field(shown, frame)
    mask = boundary_mask(polygons, frame)

    rgba = colorize(field, mode)
    rgba[..., 3] *= mask
    image = Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8), mode="RGBA")
    buf = io.BytesIO()
    image.save(buf, format="PNG", compress_level=3)

    # границы значений берём по узлам, а не по сглаженному полю: так они точнее
    node_values = [p[2] for p in shown]
    return Rendered(png=buf.getvalue(), vmin=float(min(node_values)), vmax=float(max(node_values)))
