"""HTTP-слой visualization_service: заголовки, время, статика, границы режимов."""
from datetime import datetime

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from config import settings  # noqa: E402
from main import app  # noqa: E402
from services.frames import FrameService  # noqa: E402
from tests.helpers import FakeClient  # noqa: E402

AT = {"at": "2026-11-06T12:00:00Z"}


def make(**kwargs):
    """Возвращает (HTTP-клиент, подставной клиент данных), чтобы смотреть, что у него спрашивали."""
    fake = FakeClient(**kwargs)
    app.state.frames = FrameService(fake)      # без `with`: lifespan не запускается
    return TestClient(app), fake


def test_health():
    client, _ = make()
    assert client.get("/health").json() == {"status": "ok"}


def test_range_returns_upstream_range_and_503_when_down():
    client, fake = make()
    assert client.get("/api/range").json() == fake.time_range()
    client, _ = make(fail=True)
    assert client.get("/api/range").status_code == 503


def test_config_contains_everything_page_needs():
    client, _ = make()
    body = client.get("/api/config").json()
    assert body["boundary"]["type"] == "FeatureCollection"
    assert set(body["tiles"]) == {"url", "attribution"}
    assert set(body["frame"]) == {"lat_min", "lat_max", "lon_min", "lon_max"}
    assert body["frame"]["lon_min"] < 54.0 < 57.0 < body["frame"]["lon_max"]
    for mode in body["modes"]:
        assert set(mode) == {"code", "label", "unit", "legend", "empty_hint"}
        positions = [t["pos"] for t in mode["legend"]["ticks"]]
        assert positions[0] == 0 and positions[-1] == 1 and positions == sorted(positions)


def test_frame_without_at_uses_current_hour():
    client, fake = make()
    resp = client.get("/api/frame/temperature.png")
    assert resp.status_code == 200
    asked = fake.snapshot_calls[0][1]
    assert asked.minute == 0 and asked.second == 0 and asked.year >= 2026


def test_frame_time_with_offset_is_converted_to_utc():
    client, fake = make()
    client.get("/api/frame/temperature.png", params={"at": "2026-11-06T17:40:00+05:00"})
    assert fake.snapshot_calls[0][1] == datetime(2026, 11, 6, 12, 0)


def test_frame_with_garbage_time_is_422():
    client, _ = make()
    assert client.get("/api/frame/temperature.png", params={"at": "вчера"}).status_code == 422


def test_frame_cache_headers_and_value_range():
    client, _ = make(value_fn=lambda la, lo: 10.0 + (la - 54.0))     # 10 .. 12
    resp = client.get("/api/frame/temperature.png", params=AT)
    assert resp.headers["cache-control"] == f"public, max-age={int(settings.cache_ttl)}"
    assert float(resp.headers["x-value-min"]) == pytest.approx(10.0, abs=0.001)
    assert float(resp.headers["x-value-max"]) == pytest.approx(12.0, abs=0.001)


def test_pressure_header_is_in_mmhg():
    client, _ = make(value_fn=lambda la, lo: 1000.0)
    resp = client.get("/api/frame/pressure.png", params=AT)
    assert float(resp.headers["x-value-max"]) == pytest.approx(750.062, abs=0.001)


@pytest.mark.parametrize("mode, value, empty", [
    ("precipitation", 0.05, "1"),     # ниже порога 0.1 мм/ч
    ("precipitation", 0.2, "0"),
    ("snow_depth", 0.5, "1"),         # ниже порога 1 см
    ("snow_depth", 5.0, "0"),
    ("temperature", -50.0, "0"),      # у температуры подсказки "пусто" нет
])
def test_empty_flag_depends_on_threshold(mode, value, empty):
    client, _ = make(value_fn=lambda la, lo: value)
    assert client.get(f"/api/frame/{mode}.png", params=AT).headers["x-empty"] == empty


def test_unknown_mode_lists_allowed_modes():
    client, _ = make()
    resp = client.get("/api/frame/humidity.png", params=AT)
    assert resp.status_code == 404
    assert "temperature" in resp.json()["detail"]


def test_wind_mode_asks_for_wind_speed():
    client, fake = make()
    client.get("/api/frame/wind.png", params=AT)
    assert fake.snapshot_calls[0][0] == "wind_speed"


def test_static_files_are_served():
    client, _ = make()
    for path in ("/static/app.js", "/static/style.css", "/static/index.html"):
        assert client.get(path).status_code == 200
    assert client.get("/static/no-such-file.css").status_code == 404


def test_openapi_describes_frame_endpoint():
    client, _ = make()
    assert "/api/frame/{mode}.png" in client.get("/openapi.json").json()["paths"]

def test_root_serves_the_page():
    client, _ = make()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]