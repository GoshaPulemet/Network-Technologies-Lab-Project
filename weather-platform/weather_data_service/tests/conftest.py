"""Общие фикстуры для новых тестов. pytest подхватывает этот файл сам, импортировать его не нужно.

Каждый тест получает СВОЮ чистую БД в памяти, поэтому тесты не влияют друг на друга.
(Существующий tests/test_api.py объявляет такие же фикстуры у себя - они просто перекрывают эти.)
"""
import dataclasses

import pytest

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from config import settings
from database.connections import get_session
from main import app
from models.weather import Location, WeatherObservation
from services.sources import manual_source


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
    yield TestClient(app)          # без `with`: lifespan (seed/sync) не запускается
    app.dependency_overrides.clear()


@pytest.fixture()
def cfg():
    """Настройки для тестов сбора: по одной точке в запросе и без пауз."""
    return dataclasses.replace(settings, request_chunk=1, archive_chunk=1, request_pause=0)


@pytest.fixture()
def add_location(engine):
    """add_location('Уфа', 'city', 54.74, 55.97) -> id новой локации."""
    def _add(name="Уфа", kind="city", lat=54.74, lon=55.97):
        with Session(engine) as s:
            loc = Location(name=name, kind=kind, latitude=lat, longitude=lon)
            s.add(loc)
            s.commit()
            s.refresh(loc)
            return loc.id
    return _add


@pytest.fixture()
def add_observation(engine):
    """add_observation(location_id, datetime(...), temperature=5.0) -> id наблюдения."""
    def _add(location_id, observed_at, **values):
        with Session(engine) as s:
            obs = WeatherObservation(location_id=location_id, source_id=manual_source(s).id,
                                     observed_at=observed_at, **values)
            s.add(obs)
            s.commit()
            s.refresh(obs)
            return obs.id
    return _add


@pytest.fixture()
def count_rows(engine):
    """count_rows(Location) -> сколько строк в таблице."""
    def _count(model):
        with Session(engine) as s:
            return len(s.exec(select(model)).all())
    return _count
