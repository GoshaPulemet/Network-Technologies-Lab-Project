"""Клиент Open-Meteo на подставном HTTP-транспорте (реальная сеть не нужна)."""
from datetime import date

import pytest

httpx = pytest.importorskip("httpx")

from services.openmeteo import OpenMeteoClient, OpenMeteoError  # noqa: E402


def _hourly(n=2):
    return {"hourly": {
        "time": [f"2026-11-06T0{i}:00" for i in range(n)],
        "temperature_2m": [float(i) for i in range(n)],
        "weather_code": [3] * n,
    }}


def _client(handler, **kw):
    return OpenMeteoClient(http=httpx.Client(transport=httpx.MockTransport(handler)),
                           sleep=lambda s: None, **kw)


def test_multi_location_request_and_parsing():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json=[_hourly(), _hourly()])

    result = _client(handler).fetch_forecast([(54.7, 55.9), (53.6, 55.9)], forecast_days=3, past_days=1)
    assert len(result) == 2 and result[0][1]["temperature"] == 1.0
    assert seen["latitude"] == "54.7000,53.6000"
    assert seen["timezone"] == "UTC" and seen["wind_speed_unit"] == "ms"
    assert seen["forecast_days"] == "3" and seen["past_days"] == "1"
    assert "snow_depth" in seen["hourly"] and "weather_code" in seen["hourly"]


def test_single_location_returns_object_not_list():
    client = _client(lambda r: httpx.Response(200, json=_hourly()))
    assert len(client.fetch_forecast([(54.7, 55.9)], 1)) == 1


def test_archive_uses_dates():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        seen["host"] = request.url.host
        return httpx.Response(200, json=_hourly())

    _client(handler).fetch_archive([(54.7, 55.9)], date(2025, 1, 1), date(2025, 1, 31))
    assert seen["host"] == "archive-api.open-meteo.com"
    assert seen["start_date"] == "2025-01-01" and seen["end_date"] == "2025-01-31"


def test_retries_on_server_error_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, json=_hourly())

    assert len(_client(handler).fetch_forecast([(54.7, 55.9)], 1)) == 1
    assert calls["n"] == 3


def test_client_error_is_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, json={"error": True, "reason": "bad variable"})

    with pytest.raises(OpenMeteoError, match="bad variable"):
        _client(handler).fetch_forecast([(54.7, 55.9)], 1)
    assert calls["n"] == 1
