"""/sync/*, /meta/*, /health, CORS и запуск сервиса (lifespan).
Реальные загрузки не запускаются: фоновые задачи подменены записывающими заглушками."""
import dataclasses
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import database.connections as connections
import main
from config import settings
from models.weather import ImportBatch, Location
from services.sources import manual_source, open_meteo_source


@pytest.fixture()
def jobs_log(monkeypatch):
    """Вместо реальных загрузок - заглушки, которые просто записывают, что их вызвали."""
    log = []
    monkeypatch.setattr("routes.sync.run_forecast_job", lambda: log.append("forecast"))
    monkeypatch.setattr("routes.sync.run_archive_job", lambda a, b: log.append(("archive", a, b)))
    monkeypatch.setattr("routes.sync.is_sync_running", lambda: False)
    return log


def add_batch(engine, **fields):
    with Session(engine) as s:
        s.add(ImportBatch(source_id=manual_source(s).id, kind="forecast", **fields))
        s.commit()


# ---------- /sync/forecast ----------
def test_forecast_sync_is_started_in_background(client, jobs_log):
    resp = client.post("/sync/forecast")
    assert resp.status_code == 202
    assert jobs_log == ["forecast"]


def test_forecast_sync_conflicts_when_another_is_running(client, jobs_log, monkeypatch):
    monkeypatch.setattr("routes.sync.is_sync_running", lambda: True)
    assert client.post("/sync/forecast").status_code == 409
    assert jobs_log == []


# ---------- /sync/archive ----------
def test_archive_sync_is_started(client, jobs_log):
    resp = client.post("/sync/archive", params={"date_from": "2025-01-01", "date_to": "2025-01-10"})
    assert resp.status_code == 202
    assert jobs_log == [("archive", date(2025, 1, 1), date(2025, 1, 10))]


def test_archive_period_limit_is_400_days(client, jobs_log):
    start = date(2024, 1, 1)
    ok = client.post("/sync/archive", params={"date_from": start.isoformat(), "date_to": (start + timedelta(days=400)).isoformat()})
    too_long = client.post("/sync/archive", params={"date_from": start.isoformat(), "date_to": (start + timedelta(days=401)).isoformat()})
    assert ok.status_code == 202 and too_long.status_code == 400
    assert len(jobs_log) == 1


def test_archive_rejects_reversed_period(client, jobs_log):
    resp = client.post("/sync/archive", params={"date_from": "2025-02-01", "date_to": "2025-01-01"})
    assert resp.status_code == 400 and jobs_log == []


def test_archive_rejects_period_not_yet_available(client, jobs_log):
    start = date.today() + timedelta(days=1)
    resp = client.post("/sync/archive", params={"date_from": start.isoformat(), "date_to": (start + timedelta(days=1)).isoformat()})
    assert resp.status_code == 400 and "Архив" in resp.json()["detail"]
    assert jobs_log == []


def test_archive_requires_both_dates(client, jobs_log):
    assert client.post("/sync/archive", params={"date_from": "2025-01-01"}).status_code == 422


def test_archive_conflicts_when_another_is_running(client, jobs_log, monkeypatch):
    monkeypatch.setattr("routes.sync.is_sync_running", lambda: True)
    resp = client.post("/sync/archive", params={"date_from": "2025-01-01", "date_to": "2025-01-02"})
    assert resp.status_code == 409 and jobs_log == []


# ---------- /sync/batches ----------
def test_batches_are_newest_first_and_limited(client, engine):
    for hour in (1, 2, 3):
        add_batch(engine, status="ok", started_at=datetime(2026, 11, 6, hour))
    got = client.get("/sync/batches").json()
    assert [b["started_at"] for b in got] == ["2026-11-06T03:00:00", "2026-11-06T02:00:00", "2026-11-06T01:00:00"]
    assert len(client.get("/sync/batches", params={"limit": 1}).json()) == 1


def test_batches_empty_and_bad_limit(client):
    assert client.get("/sync/batches").json() == []
    assert client.get("/sync/batches", params={"limit": 0}).status_code == 422
    assert client.get("/sync/batches", params={"limit": 101}).status_code == 422


# ---------- /meta ----------
def test_meta_parameters_lists_all_with_units(client):
    items = client.get("/meta/parameters").json()
    assert len(items) == 8
    assert all(set(i) == {"code", "label", "unit"} for i in items)
    assert {i["code"]: i["unit"] for i in items}["pressure"] == "гПа"


def test_meta_sources(client, engine):
    assert client.get("/meta/sources").json() == []
    with Session(engine) as s:
        open_meteo_source(s)
        manual_source(s)
    sources = {x["code"]: x for x in client.get("/meta/sources").json()}
    assert set(sources) == {"open-meteo", "manual"}
    assert "CC BY" in sources["open-meteo"]["license"]


def test_meta_boundary_is_geojson_with_source(client):
    body = client.get("/meta/boundary").json()
    feature = body["features"][0]
    assert feature["geometry"]["type"] == "MultiPolygon" and feature["geometry"]["coordinates"]
    assert feature["properties"]["source"] in ("file", "builtin")
    assert feature["properties"]["name"] == "Республика Башкортостан"


# ---------- main ----------
def test_health_and_redirect_to_docs(client):
    assert client.get("/health").json() == {"status": "ok"}
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307) and resp.headers["location"].endswith("/docs")


def test_cors_header_for_browser_pages(client):
    resp = client.get("/health", headers={"Origin": "http://localhost:8002"})
    assert resp.headers["access-control-allow-origin"] in ("*", "http://localhost:8002")


def test_interrupted_batches_are_closed(engine, monkeypatch):
    monkeypatch.setattr(main, "engine_url", engine)
    add_batch(engine, status="running")
    add_batch(engine, status="ok", started_at=datetime(2026, 11, 6, 1))
    main._close_interrupted_batches()
    with Session(engine) as s:
        batches = {b.status: b for b in s.exec(select(ImportBatch)).all()}
    assert set(batches) == {"error", "ok"}
    assert batches["error"].finished_at is not None and "прервано" in batches["error"].error
    assert batches["ok"].error is None


def test_startup_closes_stale_batches_and_seeds_locations(engine, monkeypatch, count_rows):
    monkeypatch.setattr(main, "engine_url", engine)
    monkeypatch.setattr(connections, "engine_url", engine)
    monkeypatch.setattr(main, "settings", dataclasses.replace(settings, auto_seed=True, auto_sync=False, grid_step=1.0))
    add_batch(engine, status="running")

    with TestClient(main.app) as live:           # `with` запускает lifespan, как при настоящем старте
        assert live.get("/health").status_code == 200

    assert count_rows(Location) > 0
    with Session(engine) as s:
        assert [b.status for b in s.exec(select(ImportBatch)).all()] == ["error"]
