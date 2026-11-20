"""HTTP-слой visualization_service на подставном клиенте (weather_data_service не нужен)."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from services.frames import FrameService  # noqa: E402
from tests.helpers import FakeClient  # noqa: E402


def make_client(**kwargs) -> TestClient:
    app.state.frames = FrameService(FakeClient(**kwargs))   # без `with`: lifespan не запускается
    return TestClient(app)


def test_config_describes_modes_frame_and_range():
    body = make_client().get("/api/config").json()
    assert [m["code"] for m in body["modes"]] == ["precipitation", "temperature", "wind", "pressure", "snow_depth"]
    temp = next(m for m in body["modes"] if m["code"] == "temperature")
    assert temp["legend"]["ticks"][0]["value"] == -40 and temp["legend"]["ticks"][-1]["value"] == 40
    assert body["default_mode"] == "temperature"
    assert body["frame"]["lat_min"] < 54.0 < 56.0 < body["frame"]["lat_max"]
    assert body["time_range"]["first"] == "2026-11-05T00:00:00Z"
    assert body["cities"][0]["name"] == "Уфа"
    assert body["utc_offset_hours"] == 5


def test_frame_returns_png_with_headers():
    resp = make_client().get("/api/frame/temperature.png", params={"at": "2026-11-06T12:00:00Z"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG")
    assert float(resp.headers["x-value-max"]) == 10.0
    assert resp.headers["x-empty"] == "0"


def test_dry_precipitation_is_marked_empty():
    resp = make_client(value_fn=lambda la, lo: 0.0).get(
        "/api/frame/precipitation.png", params={"at": "2026-11-06T12:00:00Z"})
    assert resp.status_code == 200
    assert resp.headers["x-empty"] == "1"


def test_unknown_mode_is_404():
    assert make_client().get("/api/frame/humidity.png").status_code == 404


def test_no_data_is_404():
    resp = make_client(empty=True).get("/api/frame/temperature.png", params={"at": "2026-11-06T12:00:00Z"})
    assert resp.status_code == 404


def test_data_service_down_is_503():
    client = make_client(fail=True)
    assert client.get("/api/frame/temperature.png", params={"at": "2026-11-06T12:00:00Z"}).status_code == 503
    assert client.get("/api/config").status_code == 503


def test_index_page_is_served():
    resp = make_client().get("/")
    assert resp.status_code == 200 and "text/html" in resp.headers["content-type"]
