"""FrameService: кэш, добор городов при пустой сетке, ошибки."""
from datetime import datetime, timedelta, timezone

from clients.data_service import DataServiceError
from services.frames import FrameService, NoDataError, floor_hour_utc, polygons_from_geojson
from tests.helpers import FakeClient, square_geojson

AT = datetime(2026, 11, 6, 12, 0)


def _raises(exc, fn, *a):
    try:
        fn(*a)
    except exc:
        return True
    return False


def test_floor_hour_handles_timezones():
    aware = datetime(2026, 11, 6, 17, 40, 12, tzinfo=timezone(timedelta(hours=5)))
    assert floor_hour_utc(aware) == datetime(2026, 11, 6, 12, 0)
    assert floor_hour_utc(datetime(2026, 11, 6, 12, 59, 59)) == AT


def test_polygons_from_geojson():
    polys = polygons_from_geojson(square_geojson())
    assert len(polys) == 1 and len(polys[0][0]) == 5


def test_same_frame_is_rendered_once():
    client = FakeClient()
    svc = FrameService(client)
    first = svc.render("temperature", AT)
    again = svc.render("temperature", AT + timedelta(minutes=25))    # тот же час
    assert first is again
    assert len(client.snapshot_calls) == 1
    svc.render("wind", AT)                                           # другой режим - новый запрос
    assert len(client.snapshot_calls) == 2


def test_mode_is_mapped_to_data_parameter():
    client = FakeClient()
    FrameService(client).render("wind", AT)
    assert client.snapshot_calls[0][0] == "wind_speed"


def test_falls_back_to_cities_when_grid_is_empty():
    client = FakeClient(only_cities=True)
    # сетки нет, "all" отдаёт точки: у подставного клиента они приходят для kind != grid
    FrameService(client).render("temperature", AT)
    assert [c[2] for c in client.snapshot_calls] == ["grid", "all"]


def test_no_data_raises():
    assert _raises(NoDataError, FrameService(FakeClient(empty=True)).render, "temperature", AT)


def test_upstream_failure_is_propagated():
    assert _raises(DataServiceError, FrameService(FakeClient(fail=True)).render, "temperature", AT)
