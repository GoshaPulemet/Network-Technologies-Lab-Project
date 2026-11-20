"""DataServiceClient: какие адреса и параметры уходят в weather_data_service, как обрабатываются ошибки."""
from datetime import datetime

import pytest

httpx = pytest.importorskip("httpx")

from clients.data_service import DataServiceClient, DataServiceError  # noqa: E402


def make(handler) -> DataServiceClient:
    return DataServiceClient(base_url="http://data.test", transport=httpx.MockTransport(handler))


def recorder(payload):
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=payload)

    return seen, handler


def test_time_range_path():
    seen, handler = recorder({"first": None, "last": None, "updated_at": None})
    make(handler).time_range()
    assert seen["path"] == "/observation/range"


def test_boundary_path():
    seen, handler = recorder({"type": "FeatureCollection", "features": []})
    make(handler).boundary()
    assert seen["path"] == "/meta/boundary"


def test_cities_ask_only_for_cities_with_big_limit():
    seen, handler = recorder([])
    make(handler).cities()
    assert seen["path"] == "/location/"
    assert seen["params"] == {"kind": "city", "limit": "1000"}


def test_snapshot_path_and_default_kind_is_grid():
    seen, handler = recorder({"count": 0, "points": []})
    make(handler).snapshot("wind_speed", datetime(2026, 11, 6, 12))
    assert seen["path"] == "/observation/snapshot"
    assert seen["params"]["kind"] == "grid" and seen["params"]["parameter"] == "wind_speed"


def test_snapshot_drops_microseconds():
    seen, handler = recorder({"count": 0, "points": []})
    make(handler).snapshot("temperature", datetime(2026, 11, 6, 12, 0, 0, 999999))
    assert seen["params"]["at"] == "2026-11-06T12:00:00Z"


def test_none_params_are_not_sent():
    seen, handler = recorder({})
    make(handler)._get("/x", a=1, b=None)          # приватный метод, но логика важная
    assert seen["params"] == {"a": "1"}


def test_error_keeps_status_code_and_truncates_body():
    client = make(lambda request: httpx.Response(404, text="x" * 1000))
    with pytest.raises(DataServiceError) as info:
        client.boundary()
    assert info.value.status_code == 404
    assert "404" in str(info.value)
    assert len(str(info.value)) < 300


def test_network_error_has_no_status_code():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(DataServiceError) as info:
        make(handler).time_range()
    assert info.value.status_code is None


def test_success_returns_parsed_json():
    _, handler = recorder({"first": "2026-11-05T00:00:00Z"})
    assert make(handler).time_range() == {"first": "2026-11-05T00:00:00Z"}
