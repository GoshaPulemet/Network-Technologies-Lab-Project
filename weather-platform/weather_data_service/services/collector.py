"""Сбор данных из Open-Meteo и сохранение в БД (идемпотентно: повторная загрузка обновляет строки)."""
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from config import ARCHIVE_LAG_DAYS, Settings
from models.weather import ImportBatch, Location, WeatherObservation, utc_now
from services.parameters import PARAMETERS
from services.sources import open_meteo_source

MAX_CONSECUTIVE_FAILURES = 2

_KEY_COLUMNS = ["location_id", "observed_at", "source_id"]
_UPDATE_COLUMNS = (
    ["is_forecast", "fetched_at", "weather_code", "weather_condition"] + list(PARAMETERS.keys())
)


# ---------- запись в БД ----------
def upsert_observations(session: Session, rows: List[dict]) -> int:
    """INSERT ... ON CONFLICT DO UPDATE по (location_id, observed_at, source_id)."""
    if not rows:
        return 0
    stmt = sqlite_insert(WeatherObservation.__table__)
    stmt = stmt.on_conflict_do_update(
        index_elements=_KEY_COLUMNS,
        set_={col: stmt.excluded[col] for col in _UPDATE_COLUMNS},
    )
    session.connection().execute(stmt, rows)
    return len(rows)


def build_rows(location_id: uuid.UUID, source_id: uuid.UUID, hourly: List[dict],
               is_forecast: bool, fetched_at: datetime) -> List[dict]:
    rows = []
    for h in hourly:
        values: Dict[str, object] = {code: h.get(code) for code in PARAMETERS}
        if all(v is None for v in values.values()):
            continue  # пустую строку (все значения null) хранить незачем
        rows.append({
            "id": uuid.uuid4(),
            "location_id": location_id,
            "source_id": source_id,
            "observed_at": h["observed_at"],
            "is_forecast": is_forecast,
            "fetched_at": fetched_at,
            "weather_code": h.get("weather_code"),
            "weather_condition": h.get("weather_condition"),
            **values,
        })
    return rows


# ---------- общий цикл загрузки ----------
def _run_sync(session: Session, *, kind: str, is_forecast: bool, chunk_size: int,
              fetch: Callable[[list], List[List[dict]]], pause: float,
              sleep: Callable[[float], None],
              period_from=None, period_to=None) -> ImportBatch:
    source_id = open_meteo_source(session).id
    locations = session.exec(
        select(Location).order_by(Location.kind, Location.latitude, Location.longitude)
    ).all()
    # Копируем в простые кортежи: объекты ORM "протухают" после commit
    targets = [(loc.id, loc.latitude, loc.longitude) for loc in locations]

    batch = ImportBatch(source_id=source_id, kind=kind, locations_total=len(targets),
                        period_from=period_from, period_to=period_to)
    session.add(batch)
    session.commit()
    batch_id = batch.id

    errors: List[str] = []
    rows_total = 0
    chunks_ok = 0
    consecutive_failures = 0
    fetched_at = utc_now()

    if not targets:
        errors.append("В БД нет локаций. Выполните: python cli.py seed")

    for start in range(0, len(targets), chunk_size):
        chunk = targets[start:start + chunk_size]
        coords = [(lat, lon) for _, lat, lon in chunk]
        try:
            per_location = fetch(coords)
            rows: List[dict] = []
            for (loc_id, _, _), hourly in zip(chunk, per_location):
                rows.extend(build_rows(loc_id, source_id, hourly, is_forecast, fetched_at))
            rows_total += upsert_observations(session, rows)
            session.commit()
            chunks_ok += 1
            consecutive_failures = 0
        except Exception as exc:  # noqa: BLE001 - любую ошибку записываем в журнал
            session.rollback()
            errors.append(f"точки {start + 1}-{start + len(chunk)}: {exc}")
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                errors.append("загрузка прервана после нескольких ошибок подряд")
                break
        if pause and start + chunk_size < len(targets):
            sleep(pause)

    batch = session.get(ImportBatch, batch_id)
    batch.rows_upserted = rows_total
    batch.finished_at = utc_now()
    if not errors:
        batch.status = "ok"
    elif chunks_ok > 0:
        batch.status = "partial"
    else:
        batch.status = "error"
    batch.error = "; ".join(errors)[:1000] if errors else None
    session.add(batch)
    session.commit()
    session.refresh(batch)
    return batch


# ---------- публичные операции ----------
def sync_forecast(session: Session, client, cfg: Settings,
                  sleep: Callable[[float], None] = time.sleep) -> ImportBatch:
    """Обновить прогноз (и последние past_days суток) для всех локаций."""
    return _run_sync(
        session, kind="forecast", is_forecast=True, chunk_size=cfg.request_chunk,
        fetch=lambda coords: client.fetch_forecast(coords, cfg.forecast_days, cfg.past_days),
        pause=cfg.request_pause, sleep=sleep,
    )


def clamp_archive_period(date_from: date, date_to: date) -> tuple:
    """Архив ERA5 отстаёт на несколько суток, поэтому обрезаем конец периода."""
    latest = utc_now().date() - timedelta(days=ARCHIVE_LAG_DAYS)
    date_to = min(date_to, latest)
    if date_from > date_to:
        raise ValueError(f"Архив доступен не позже {latest.isoformat()}")
    return date_from, date_to


def sync_archive(session: Session, client, cfg: Settings, date_from: date, date_to: date,
                 sleep: Callable[[float], None] = time.sleep) -> ImportBatch:
    """Загрузить исторические данные (реанализ) за период для всех локаций."""
    date_from, date_to = clamp_archive_period(date_from, date_to)
    return _run_sync(
        session, kind="archive", is_forecast=False, chunk_size=cfg.archive_chunk,
        fetch=lambda coords: client.fetch_archive(coords, date_from, date_to),
        pause=cfg.request_pause, sleep=sleep,
        period_from=datetime.combine(date_from, datetime.min.time()),
        period_to=datetime.combine(date_to, datetime.min.time()),
    )
