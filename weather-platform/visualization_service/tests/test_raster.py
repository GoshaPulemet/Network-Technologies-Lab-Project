"""Растеризация слоя: размеры, маска по границе, цвета, интерполяция."""
import io
import math

import numpy as np
from PIL import Image

from services.palettes import MODES, hex_to_rgb
from services.raster import colorize, make_frame, merc_y, render_png, smooth_field
from tests.helpers import SQUARE, grid_points


def _points(fn):
    return [(p["latitude"], p["longitude"], p["value"]) for p in grid_points(fn)]


def _decode(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))


def test_frame_keeps_mercator_aspect():
    frame = make_frame(SQUARE, 800)
    assert frame.width == 800
    expected = 800 * (merc_y(frame.lat_max) - merc_y(frame.lat_min)) / math.radians(frame.lon_max - frame.lon_min)
    assert abs(frame.height - expected) <= 1


def test_png_has_frame_size_and_transparent_outside_boundary():
    frame = make_frame(SQUARE, 400)
    out = render_png(_points(lambda la, lo: 10.0), MODES["temperature"], SQUARE, frame)
    img = _decode(out.png)
    assert img.shape[:2] == (frame.height, frame.width)
    assert img[2, 2, 3] == 0                                  # угол - за границей
    cx, cy = frame.to_pixels(55.5, 55.0)
    assert img[int(cy), int(cx), 3] > 150                     # центр - внутри, слой почти непрозрачен


def test_constant_field_gives_exact_stop_color():
    frame = make_frame(SQUARE, 300)
    out = render_png(_points(lambda la, lo: 10.0), MODES["temperature"], SQUARE, frame)   # 10 °C - опорная точка
    cx, cy = frame.to_pixels(55.5, 55.0)
    r, g, b, a = _decode(out.png)[int(cy), int(cx)]
    assert (r, g, b) == hex_to_rgb("#4fa65a")
    assert abs(a - 0.82 * 255) <= 1
    assert out.vmin == out.vmax == 10.0


def test_warmer_side_is_warmer_color():
    frame = make_frame(SQUARE, 400)
    out = render_png(_points(lambda la, lo: -10 + (lo - 54.0) * 10), MODES["temperature"], SQUARE, frame)
    img = _decode(out.png)
    x1, y1 = frame.to_pixels(54.5, 55.0)
    x2, y2 = frame.to_pixels(56.5, 55.0)
    west, east = img[int(y1), int(x1)], img[int(y2), int(x2)]
    assert west[2] > west[0]          # холодно - больше синего
    assert east[0] > east[2]          # тепло - больше красного


def test_precipitation_is_transparent_where_dry():
    frame = make_frame(SQUARE, 300)
    out = render_png(_points(lambda la, lo: 0.0), MODES["precipitation"], SQUARE, frame)
    assert _decode(out.png)[..., 3].max() == 0


def test_pressure_is_shown_in_mmhg():
    frame = make_frame(SQUARE, 200)
    out = render_png(_points(lambda la, lo: 1000.0), MODES["pressure"], SQUARE, frame)
    assert abs(out.vmax - 750.062) < 0.01


def test_colorize_clamps_outside_scale():
    mode = MODES["temperature"]
    low, high = colorize(np.array([-100.0]), mode)[0], colorize(np.array([100.0]), mode)[0]
    assert tuple(low[:3]) == hex_to_rgb(mode.stops[0][1])
    assert tuple(high[:3]) == hex_to_rgb(mode.stops[-1][1])


def test_smooth_field_reproduces_constant_and_stays_in_range():
    pts = np.asarray(_points(lambda la, lo: 3.0 + la))
    lats, lons, vals = pts[:, 0], pts[:, 1], pts[:, 2]
    q_lat = np.array([54.3, 55.1, 55.9, 60.0])      # последняя точка далеко от узлов
    q_lon = np.array([55.0, 55.5, 56.0, 70.0])
    got = smooth_field(lats, lons, vals, q_lat, q_lon, sigma_km=20.0, lat_mid=55.0)
    assert np.all(np.isfinite(got))
    assert vals.min() <= got.min() and got.max() <= vals.max()
    assert abs(got[1] - (3.0 + 55.1)) < 0.3          # гладкий градиент воспроизводится
