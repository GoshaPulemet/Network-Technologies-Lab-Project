"""Тесты API и сбора данных на SQLite в памяти и подставном клиенте Open-Meteo."""
import dataclasses
from datetime import datetime

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlmodel")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine, select  # noqa: E402

from config import settings  # noqa: E402
from database.connections import get_session  # noqa: E402
from main import app  # noqa: E402
from models.weather import ImportBatch, Location, WeatherObservation  # noqa: E402
from services.collector import sync_forecast  # noqa: E402


class FakeClient:
    """Вместо сети: для каждой точки отдаёт 3 часа данных."""
    def __init__(self, fail=False):
        self.fail = fail

    def fetch_forecast(self, coords, forecast_days, past_days):
        if self.fail:
            raise RuntimeError("API недоступен")
        return [
            [{"observed_at": datetime(2026, 11, 6, h), "temperature": 5.0 + i + h,
              "snow_depth": 12.0, "weather_code": 3, "weather_condition": "overcast"}
             for h in range(3)]
            for i, _ in enumerate(coords)
        ]


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture()
def client(engine):
    def override():
        with Session(engine) as s:
            yield s
    app.dependency_overrides[get_session] = override
    yield TestClient(app)   # без `with`: lifespan (seed/sync) не запускается
    app.dependency_overrides.clear()


@pytest.fixture()
def cfg():
    return dataclasses.replace(settings, request_chunk=1, request_pause=0)


def _add_locations(engine):
    with Session(engine) as s:
        s.add(Location(name="Уфа", kind="city", latitude=54.74, longitude=55.97))
        s.add(Location(name="Узел A", kind="grid", latitude=53.5, longitude=56.0))
        s.commit()


def test_sync_is_idempotent_and_logged(engine, cfg):
    _add_locations(engine)
    with Session(engine) as s:
        batch = sync_forecast(s, FakeClient(), cfg, sleep=lambda x: None)
        assert batch.status == "ok" and batch.rows_upserted == 6
        sync_forecast(s, FakeClient(), cfg, sleep=lambda x: None)
        assert len(s.exec(select(WeatherObservation)).all()) == 6   # дубликатов нет
        assert len(s.exec(select(ImportBatch)).all()) == 2


def test_sync_failure_is_recorded_and_aborts(engine, cfg):
    _add_locations(engine)
    with Session(engine) as s:
        batch = sync_forecast(s, FakeClient(fail=True), cfg, sleep=lambda x: None)
        assert batch.status == "error" and "API недоступен" in batch.error


def test_sync_without_locations_reports_error(engine, cfg):
    with Session(engine) as s:
        assert sync_forecast(s, FakeClient(), cfg, sleep=lambda x: None).status == "error"


def test_snapshot_series_range_and_nearest(engine, client, cfg):
    _add_locations(engine)
    with Session(engine) as s:
        sync_forecast(s, FakeClient(), cfg, sleep=lambda x: None)

    snap = client.get("/observation/snapshot", params={
        "parameter": "temperature", "at": "2026-11-06T01:30:00Z", "kind": "all"}).json()
    assert snap["count"] == 2 and snap["unit"] == "°C" and snap["at"] == "2026-11-06T01:00:00Z"

    grid_only = client.get("/observation/snapshot", params={
        "parameter": "snow_depth", "at": "2026-11-06T00:00:00Z"}).json()   # kind=grid по умолчанию
    assert grid_only["count"] == 1 and grid_only["points"][0]["value"] == 12.0

    assert client.get("/observation/snapshot", params={"parameter": "nope"}).status_code == 400

    loc_id = client.get("/location/", params={"kind": "city"}).json()[0]["id"]
    series = client.get("/observation/series",
                        params={"location_id": loc_id, "parameter": "temperature"}).json()
    assert [p["value"] for p in series["points"]] == [5.0, 6.0, 7.0]
    assert series["points"][0]["t"] == "2026-11-06T00:00:00Z"

    rng = client.get("/observation/range").json()
    assert rng["first"] == "2026-11-06T00:00:00Z" and rng["last"] == "2026-11-06T02:00:00Z"

    near = client.get("/location/nearest", params={"lat": 54.7, "lon": 56.0}).json()
    assert near["name"] == "Уфа" and near["distance_km"] < 10
    assert client.get("/location/nearest", params={"lat": 55.75, "lon": 37.6}).status_code == 400


def test_location_crud_and_bbox_validation(client):
    ok = client.post("/location/new", json={"name": "Тест", "latitude": 54.0, "longitude": 56.0})
    assert ok.status_code == 200
    loc_id = ok.json()["id"]
    assert client.post("/location/new", json={"name": "Дубль", "latitude": 54.0, "longitude": 56.0}).status_code == 409
    assert client.post("/location/new", json={"name": "Москва", "latitude": 55.75, "longitude": 37.6}).status_code == 400
    assert client.put(f"/location/edit/{loc_id}", json={"name": "Новое"}).json()["name"] == "Новое"
    assert client.delete(f"/location/delete/{loc_id}").status_code == 200
    assert client.get(f"/location/{loc_id}").status_code == 404


def test_manual_observation_and_meta(engine, client):
    _add_locations(engine)
    loc_id = client.get("/location/", params={"kind": "city"}).json()[0]["id"]
    r = client.post("/observation/new", json={
        "location_id": loc_id, "observed_at": "2026-11-06T12:00:00", "temperature": 3.5, "weather_code": 71})
    assert r.status_code == 200
    again = client.post("/observation/new", json={
        "location_id": loc_id, "observed_at": "2026-11-06T12:00:00", "temperature": 4.0})
    assert again.status_code == 409
    codes = [p["code"] for p in client.get("/meta/parameters").json()]
    assert "snow_depth" in codes
    boundary = client.get("/meta/boundary").json()
    assert boundary["features"][0]["geometry"]["type"] == "MultiPolygon"
