"""Сбор данных (collector), первичное наполнение (seed) и фоновые задания (jobs).
Open-Meteo подменён скриптованным клиентом: сеть не нужна, ошибки происходят ровно там, где мы скажем."""
import dataclasses
import json
import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

import services.jobs as jobs
from config import ARCHIVE_LAG_DAYS, DATA_DIR
from models.weather import DataSource, ImportBatch, Location, WeatherObservation, utc_now
from services.collector import build_rows, clamp_archive_period, sync_archive, sync_forecast, upsert_observations
from services.grid import get_boundary, point_in_boundary
from services.parameters import PARAMETERS
from services.seed import delete_locations_by_kind, seed_locations
from services.sources import manual_source


class ScriptedClient:
    """Подставной Open-Meteo: каждой точке - 2 часа данных; вызовы из fail_calls (счёт с 1) падают."""

    def __init__(self, fail_calls=(), temperature=5.0):
        self.fail_calls = set(fail_calls)
        self.temperature = temperature
        self.calls = []

    def _answer(self, coords):
        self.calls.append(list(coords))
        if len(self.calls) in self.fail_calls:
            raise RuntimeError("boom")
        return [[{"observed_at": datetime(2026, 11, 6, h), "temperature": self.temperature,
                  "weather_code": None, "weather_condition": None} for h in range(2)] for _ in coords]

    def fetch_forecast(self, coords, forecast_days, past_days):
        return self._answer(coords)

    def fetch_archive(self, coords, start, end):
        return self._answer(coords)


@pytest.fixture()
def three_locations(add_location):
    add_location("A", "city", 54.0, 56.0)
    add_location("B", "city", 55.0, 56.0)
    add_location("C", "grid", 54.0, 55.0)


def no_sleep(_seconds):
    pass


# ---------- контракт ----------
def test_every_parameter_is_a_database_column():
    """Если добавить параметр в PARAMETERS и забыть колонку, снимок/ряд упадут только в бою."""
    for code in PARAMETERS:
        assert hasattr(WeatherObservation, code), code


# ---------- build_rows / upsert / clamp ----------
def test_build_rows_skips_rows_without_any_value():
    t1, t2 = datetime(2026, 11, 6, 0), datetime(2026, 11, 6, 1)
    loc_id, src_id, fetched = uuid.uuid4(), uuid.uuid4(), datetime(2026, 11, 6, 9)
    rows = build_rows(loc_id, src_id, [{"observed_at": t1, "temperature": 1.0}, {"observed_at": t2}], True, fetched)
    assert len(rows) == 1
    row = rows[0]
    assert (row["location_id"], row["source_id"], row["observed_at"]) == (loc_id, src_id, t1)
    assert row["is_forecast"] is True and row["fetched_at"] == fetched
    assert row["temperature"] == 1.0 and row["humidity"] is None


def test_upsert_nothing_returns_zero(engine):
    with Session(engine) as s:
        assert upsert_observations(s, []) == 0


def test_clamp_archive_period():
    latest = utc_now().date() - timedelta(days=ARCHIVE_LAG_DAYS)
    assert clamp_archive_period(date(2020, 1, 1), date(2020, 1, 31)) == (date(2020, 1, 1), date(2020, 1, 31))
    assert clamp_archive_period(date(2020, 1, 1), latest + timedelta(days=30)) == (date(2020, 1, 1), latest)
    with pytest.raises(ValueError, match="Архив доступен"):
        clamp_archive_period(latest + timedelta(days=1), latest + timedelta(days=3))


# ---------- sync_forecast ----------
def test_successful_sync_fills_batch_log(engine, cfg, three_locations):
    with Session(engine) as s:
        batch = sync_forecast(s, ScriptedClient(), cfg, sleep=no_sleep)
        assert batch.status == "ok" and batch.error is None
        assert batch.kind == "forecast" and batch.locations_total == 3 and batch.rows_upserted == 6
        assert batch.finished_at is not None
        assert s.get(ImportBatch, batch.id).status == "ok"


def test_second_sync_updates_values_instead_of_duplicating(engine, cfg, add_location):
    add_location()
    with Session(engine) as s:
        sync_forecast(s, ScriptedClient(temperature=5.0), cfg, sleep=no_sleep)
        sync_forecast(s, ScriptedClient(temperature=9.0), cfg, sleep=no_sleep)
        temps = [o.temperature for o in s.exec(select(WeatherObservation)).all()]
    assert temps == [9.0, 9.0]          # 2 часа, и оба обновились


def test_one_failed_chunk_gives_partial_status(engine, cfg, three_locations):
    client = ScriptedClient(fail_calls={1})
    with Session(engine) as s:
        batch = sync_forecast(s, client, cfg, sleep=no_sleep)
    assert batch.status == "partial"
    assert "точки 1-1" in batch.error and "boom" in batch.error
    assert batch.rows_upserted == 4 and len(client.calls) == 3


def test_failures_with_success_between_do_not_abort(engine, cfg, three_locations):
    client = ScriptedClient(fail_calls={1, 3})
    with Session(engine) as s:
        batch = sync_forecast(s, client, cfg, sleep=no_sleep)
    assert batch.status == "partial" and len(client.calls) == 3
    assert "прервана" not in batch.error


def test_two_failures_in_a_row_abort_the_sync(engine, cfg, three_locations):
    client = ScriptedClient(fail_calls={1, 2})
    with Session(engine) as s:
        batch = sync_forecast(s, client, cfg, sleep=no_sleep)
    assert batch.status == "error" and "прервана" in batch.error
    assert len(client.calls) == 2           # до третьей точки не дошли


def test_pause_between_chunks_but_not_after_last(engine, cfg, three_locations):
    sleeps = []
    slow = dataclasses.replace(cfg, request_pause=7)
    with Session(engine) as s:
        sync_forecast(s, ScriptedClient(), slow, sleep=sleeps.append)
    assert sleeps == [7, 7]                 # три запроса - две паузы


def test_chunk_size_groups_locations(engine, cfg, three_locations):
    client = ScriptedClient()
    two_at_a_time = dataclasses.replace(cfg, request_chunk=2)
    with Session(engine) as s:
        sync_forecast(s, client, two_at_a_time, sleep=no_sleep)
    assert [len(c) for c in client.calls] == [2, 1]


# ---------- sync_archive ----------
def test_archive_sync_is_marked_as_history(engine, cfg, add_location):
    add_location()
    with Session(engine) as s:
        batch = sync_archive(s, ScriptedClient(), cfg, date(2025, 1, 1), date(2025, 1, 10), sleep=no_sleep)
        assert batch.kind == "archive" and batch.status == "ok"
        assert batch.period_from == datetime(2025, 1, 1) and batch.period_to == datetime(2025, 1, 10)
        assert [o.is_forecast for o in s.exec(select(WeatherObservation)).all()] == [False, False]


def test_archive_sync_for_unavailable_period_fails_before_logging(engine, cfg, add_location, count_rows):
    add_location()
    tomorrow = utc_now().date() + timedelta(days=1)
    with Session(engine) as s:
        with pytest.raises(ValueError):
            sync_archive(s, ScriptedClient(), cfg, tomorrow, tomorrow, sleep=no_sleep)
    assert count_rows(ImportBatch) == 0


# ---------- seed ----------
def test_seed_creates_cities_grid_and_sources(engine):
    cities = json.loads((DATA_DIR / "cities.json").read_text(encoding="utf-8"))
    with Session(engine) as s:
        summary = seed_locations(s, 1.0)
        assert summary["cities_added"] == len(cities)
        assert summary["grid_added"] > 0 and summary["grid_step"] == 1.0
        assert summary["boundary"] in ("file", "builtin")
        assert {src.code for src in s.exec(select(DataSource)).all()} == {"open-meteo", "manual"}

        polygons, _ = get_boundary()
        for node in s.exec(select(Location).where(Location.kind == "grid")).all():
            assert point_in_boundary(node.longitude, node.latitude, list(polygons))


def test_seed_is_idempotent(engine, count_rows):
    with Session(engine) as s:
        seed_locations(s, 1.0)
    total = count_rows(Location)
    with Session(engine) as s:
        again = seed_locations(s, 1.0)
    assert again["cities_added"] == 0 and again["grid_added"] == 0
    assert count_rows(Location) == total


def test_delete_locations_by_kind_removes_observations_too(engine, count_rows):
    with Session(engine) as s:
        seed_locations(s, 1.0)
        grid_loc = s.exec(select(Location).where(Location.kind == "grid")).first()
        s.add(WeatherObservation(location_id=grid_loc.id, source_id=manual_source(s).id,
                                 observed_at=datetime(2026, 11, 6), temperature=1.0))
        s.commit()
        cities = len(s.exec(select(Location).where(Location.kind == "city")).all())
        grid = len(s.exec(select(Location).where(Location.kind == "grid")).all())

        assert delete_locations_by_kind(s, "grid") == grid
        assert delete_locations_by_kind(s, "grid") == 0
    assert count_rows(Location) == cities
    assert count_rows(WeatherObservation) == 0


# ---------- jobs ----------
@pytest.fixture()
def patched_jobs(monkeypatch, engine):
    """Подменяем клиент Open-Meteo, БД и сами синхронизации. Возвращаем список созданных клиентов."""
    created = []

    class DummyClient:
        def __init__(self):
            self.closed = False
            created.append(self)

        def close(self):
            self.closed = True

    monkeypatch.setattr(jobs, "OpenMeteoClient", DummyClient)
    monkeypatch.setattr(jobs, "engine_url", engine)
    return created


def test_busy_lock_makes_jobs_return_none():
    assert jobs._lock.acquire(blocking=False)
    try:
        assert jobs.is_sync_running() is True
        assert jobs.run_forecast_job() is None
        assert jobs.run_archive_job(date(2025, 1, 1), date(2025, 1, 2)) is None
    finally:
        jobs._lock.release()
    assert jobs.is_sync_running() is False


def test_forecast_job_returns_batch_id_and_cleans_up(monkeypatch, patched_jobs):
    batch_id = uuid.uuid4()
    monkeypatch.setattr(jobs, "sync_forecast", lambda session, client, cfg: SimpleNamespace(id=batch_id))
    assert jobs.run_forecast_job() == batch_id
    assert patched_jobs[0].closed is True
    assert jobs.is_sync_running() is False


def test_forecast_job_releases_lock_even_when_sync_crashes(monkeypatch, patched_jobs):
    def crash(session, client, cfg):
        raise RuntimeError("упало")

    monkeypatch.setattr(jobs, "sync_forecast", crash)
    with pytest.raises(RuntimeError):
        jobs.run_forecast_job()
    assert patched_jobs[0].closed is True
    assert jobs.is_sync_running() is False


def test_archive_job_swallows_period_error(monkeypatch, patched_jobs):
    def bad_period(session, client, cfg, date_from, date_to):
        raise ValueError("нет данных за период")

    monkeypatch.setattr(jobs, "sync_archive", bad_period)
    assert jobs.run_archive_job(date(2030, 1, 1), date(2030, 1, 2)) is None
    assert patched_jobs[0].closed is True and jobs.is_sync_running() is False
