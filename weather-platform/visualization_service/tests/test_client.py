"""Клиент weather_data_service на подставном HTTP-транспорте."""
from datetime import datetime

import pytest

httpx = pytest.importorskip("httpx")

from clients.data_service import DataServiceClient, DataServiceError  # noqa: E402


def make(handler) -> DataServiceClient:
    return DataServiceClient(base_url="http://data.test", transport=httpx.MockTransport(handler))


def test_snapshot_sends_utc_time_with_z():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json={"count": 0, "points": []})

    make(handler).snapshot("temperature", datetime(2026, 11, 6, 12), kind="grid")
    assert seen == {"parameter": "temperature", "at": "2026-11-06T12:00:00Z", "kind": "grid"}


def test_http_error_becomes_data_service_error():
    client = make(lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(DataServiceError) as info:
        client.time_range()
    assert info.value.status_code == 500


def test_network_error_becomes_data_service_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(DataServiceError):
        make(handler).boundary()
