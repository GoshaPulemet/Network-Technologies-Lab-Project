"""Запуск синхронизации в фоне. Одновременно выполняется не более одной загрузки."""
import threading
from datetime import date
from typing import Optional
from uuid import UUID

from sqlmodel import Session

from config import settings
from database.connections import engine_url
from services.collector import sync_archive, sync_forecast
from services.openmeteo import OpenMeteoClient

_lock = threading.Lock()


def is_sync_running() -> bool:
    return _lock.locked()


def run_forecast_job() -> Optional[UUID]:
    """Возвращает id записи журнала или None, если другая загрузка уже идёт."""
    if not _lock.acquire(blocking=False):
        return None
    client = OpenMeteoClient()
    try:
        with Session(engine_url) as session:
            return sync_forecast(session, client, settings).id
    finally:
        client.close()
        _lock.release()


def run_archive_job(date_from: date, date_to: date) -> Optional[UUID]:
    if not _lock.acquire(blocking=False):
        return None
    client = OpenMeteoClient()
    try:
        with Session(engine_url) as session:
            return sync_archive(session, client, settings, date_from, date_to).id
    except ValueError:
        return None
    finally:
        client.close()
        _lock.release()
