"""Растр: крайние случаи (пустая граница, дыры, углы кадра, единственная точка)."""
import io

import numpy as np
import pytest
from PIL import Image

from services.palettes import MODES
from services.raster import (
    Frame, boundary_mask, build_field, colorize, estimate_sigma_km, inv_merc_y,
    make_frame, merc_y, polygons_bounds, render_png,
)

SQUARE = [[[(54.0, 54.0), (57.0, 54.0), (57.0, 56.0), (54.0, 56.0)]]]
# тот же квадрат, но с дырой посередине
WITH_HOLE = [[
    [(54.0, 54.0), (57.0, 54.0), (57.0, 56.0), (54.0, 56.0)],
    [(55.0, 54.8), (56.0, 54.8), (56.0, 55.2), (55.0, 55.2)],
]]


def test_polygons_bounds_adds_padding():
    assert polygons_bounds(SQUARE, pad=0.1) == pytest.approx((53.9, 56.1, 53.9, 57.1))


def test_polygons_bounds_rejects_empty():
    with pytest.raises(ValueError):
        polygons_bounds([])
    with pytest.raises(ValueError):
        polygons_bounds([[[]]])


def test_mercator_roundtrip():
    for lat in (0.0, 45.0, 54.7, -30.0):
        assert float(inv_merc_y(merc_y(lat))) == pytest.approx(lat, abs=1e-9)


def test_frame_corners_map_to_pixel_corners():
    frame = make_frame(SQUARE, 400)
    assert frame.to_pixels(frame.lon_min, frame.lat_max) == pytest.approx((0, 0))
    assert frame.to_pixels(frame.lon_max, frame.lat_min) == pytest.approx((frame.width, frame.height))


def test_make_frame_height_is_never_degenerate():
    flat = [[[(54.0, 55.0), (57.0, 55.0), (57.0, 55.0001), (54.0, 55.0001)]]]
    assert make_frame(flat, 10).height >= 2


def test_sigma_for_single_point_and_minimum():
    one = estimate_sigma_km(np.array([55.0]), np.array([55.0]), 55.0)
    assert one == 50.0
    close = estimate_sigma_km(np.array([55.0, 55.0001]), np.array([55.0, 55.0]), 55.0)
    assert close == 10.0                                 # не меньше 10 км


def test_sigma_grows_with_spacing():
    lats = np.array([55.0, 55.0, 55.0, 55.0, 55.0])
    dense = estimate_sigma_km(lats, np.array([55.0, 55.1, 55.2, 55.3, 55.4]), 55.0)
    sparse = estimate_sigma_km(lats, np.array([55.0, 56.0, 57.0, 58.0, 59.0]), 55.0)
    assert sparse > dense


def test_boundary_mask_inside_outside_and_hole():
    frame = make_frame(WITH_HOLE, 400)
    mask = boundary_mask(WITH_HOLE, frame)
    assert mask.shape == (frame.height, frame.width)
    assert mask.min() >= 0.0 and mask.max() <= 1.0

    def at(lon, lat):
        x, y = frame.to_pixels(lon, lat)
        return mask[int(y), int(x)]

    assert at(54.5, 55.5) == pytest.approx(1.0, abs=0.01)     # внутри
    assert at(55.5, 55.0) == pytest.approx(0.0, abs=0.01)     # в дыре
    assert mask[0, 0] == 0.0                                  # угол картинки - в запасе рамки, снаружи


def test_build_field_shape_and_constant():
    frame = make_frame(SQUARE, 120)
    points = [(la, lo, 7.0) for la in (54.2, 55.0, 55.8) for lo in (54.5, 55.5, 56.5)]
    field = build_field(points, frame)
    assert field.shape == (frame.height, frame.width)
    assert np.allclose(field, 7.0, atol=0.05)


def test_render_single_point_does_not_crash():
    frame = make_frame(SQUARE, 100)
    out = render_png([(55.0, 55.5, 3.0)], MODES["temperature"], SQUARE, frame)
    assert out.png.startswith(b"\x89PNG")
    assert out.vmin == out.vmax == 3.0


def test_render_rejects_no_points():
    frame = make_frame(SQUARE, 100)
    with pytest.raises(ValueError):
        render_png([], MODES["temperature"], SQUARE, frame)


def test_render_min_max_come_from_nodes_in_display_units():
    frame = make_frame(SQUARE, 100)
    pts = [(54.5, 55.0, 990.0), (55.5, 56.0, 1020.0)]            # гПа
    out = render_png(pts, MODES["pressure"], SQUARE, frame)
    assert out.vmin == pytest.approx(990 * 0.750062, abs=1e-3)
    assert out.vmax == pytest.approx(1020 * 0.750062, abs=1e-3)


def test_png_is_rgba_with_frame_size():
    frame = make_frame(SQUARE, 150)
    out = render_png([(55.0, 55.5, 0.0)], MODES["temperature"], SQUARE, frame)
    img = Image.open(io.BytesIO(out.png))
    assert img.mode == "RGBA" and img.size == (frame.width, frame.height)


def test_colorize_interpolates_between_stops():
    mode = MODES["temperature"]                                  # 0 °C -> #35a39b, 10 °C -> #4fa65a
    mid = colorize(np.array([5.0]), mode)[0]
    assert mid[0] == pytest.approx((0x35 + 0x4F) / 2, abs=0.5)
    assert mid[1] == pytest.approx((0xA3 + 0xA6) / 2, abs=0.5)


def test_colorize_alpha_zero_where_dry():
    mode = MODES["precipitation"]
    assert colorize(np.array([0.0]), mode)[0][3] == 0.0
    assert colorize(np.array([10.0]), mode)[0][3] == pytest.approx(0.92 * 255)


def test_frame_is_immutable():
    frame = Frame(1, 2, 3, 4, 5, 6)
    with pytest.raises(Exception):
        frame.width = 10
