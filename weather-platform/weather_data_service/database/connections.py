from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from config import settings

# Модели нужно импортировать, чтобы create_all увидел таблицы
from models.weather import (  # noqa: F401
    DataSource, ImportBatch, Location, WeatherObservation,
)

_is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine_url = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    connect_args=connect_args,
)

if _is_sqlite:
    @event.listens_for(engine_url, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def conn():
    SQLModel.metadata.create_all(engine_url)


def get_session():
    with Session(engine_url) as session:
        yield session
