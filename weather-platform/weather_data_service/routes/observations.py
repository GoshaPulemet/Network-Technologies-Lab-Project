import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from database.connections import get_session
from models.weather import (
    Location, ObservationCreate, ObservationRange, Series, SeriesPoint,
    Snapshot, SnapshotPoint, WeatherObservation, utc_now,
)
from services.parameters import PARAMETERS
from services.sources import manual_source
from services.wmo import describe_weather_code

observation_router = APIRouter(tags=["Observations"])


def _naive_utc(dt: datetime) -> datetime:
    """Любое входящее время приводим к naive UTC (так оно хранится в БД)."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _iso_z(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat() + "Z"


def _get_parameter(code: str):
    param = PARAMETERS.get(code)
    if param is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown parameter '{code}'. Allowed: {', '.join(PARAMETERS)}"
        )
    return param


# ---------- READ: наблюдения с фильтрами (время - UTC) ----------
# limit=N возвращает N самых свежих наблюдений (в порядке возрастания времени)
@observation_router.get("/", response_model=List[WeatherObservation])
def retrieve_observations(
        location_id: Optional[uuid.UUID] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: Optional[int] = Query(default=None, ge=1, le=5000),
        session: Session = Depends(get_session)) -> List[WeatherObservation]:
    statement = select(WeatherObservation)
    if location_id:
        statement = statement.where(WeatherObservation.location_id == location_id)
    if date_from:
        statement = statement.where(WeatherObservation.observed_at >= _naive_utc(date_from))
    if date_to:
        statement = statement.where(WeatherObservation.observed_at <= _naive_utc(date_to))

    if limit:
        statement = statement.order_by(col(WeatherObservation.observed_at).desc()).limit(limit)
        return list(reversed(session.exec(statement).all()))

    statement = statement.order_by(col(WeatherObservation.observed_at))
    return session.exec(statement).all()


# ---------- READ: срез по всем точкам на момент времени (данные для карты) ----------
@observation_router.get("/snapshot", response_model=Snapshot)
def retrieve_snapshot(
        parameter: str,
        at: Optional[datetime] = Query(default=None, description="Момент времени, UTC. По умолчанию - текущий час"),
        kind: Optional[str] = Query(default="grid", description="grid | city | all"),
        session: Session = Depends(get_session)) -> Snapshot:
    param = _get_parameter(parameter)
    moment = _naive_utc(at) if at else utc_now()
    moment = moment.replace(minute=0, second=0, microsecond=0)

    column = getattr(WeatherObservation, parameter)
    statement = (
        select(Location.id, Location.name, Location.latitude, Location.longitude, column)
        .join(WeatherObservation, WeatherObservation.location_id == Location.id)
        .where(WeatherObservation.observed_at == moment)
        .where(column.is_not(None))
    )
    if kind and kind != "all":
        statement = statement.where(Location.kind == kind)

    points = [
        SnapshotPoint(location_id=r[0], name=r[1], latitude=r[2], longitude=r[3], value=r[4])
        for r in session.exec(statement).all()
    ]
    return Snapshot(parameter=parameter, unit=param.unit, at=_iso_z(moment),
                    count=len(points), points=points)


# ---------- READ: временной ряд параметра для точки (данные для графика) ----------
@observation_router.get("/series", response_model=Series)
def retrieve_series(
        location_id: uuid.UUID,
        parameter: str,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        session: Session = Depends(get_session)) -> Series:
    param = _get_parameter(parameter)
    if session.get(Location, location_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location with supplied ID does not exist"
        )
    column = getattr(WeatherObservation, parameter)
    statement = (
        select(WeatherObservation.observed_at, column)
        .where(WeatherObservation.location_id == location_id)
    )
    if date_from:
        statement = statement.where(WeatherObservation.observed_at >= _naive_utc(date_from))
    if date_to:
        statement = statement.where(WeatherObservation.observed_at <= _naive_utc(date_to))
    statement = statement.order_by(col(WeatherObservation.observed_at))

    points = [SeriesPoint(t=_iso_z(r[0]), value=r[1]) for r in session.exec(statement).all()]
    return Series(location_id=location_id, parameter=parameter, unit=param.unit, points=points)


# ---------- READ: за какой период есть данные (границы ползунка времени) ----------
@observation_router.get("/range", response_model=ObservationRange)
def retrieve_range(session: Session = Depends(get_session)) -> ObservationRange:
    first, last, updated = session.exec(
        select(
            func.min(WeatherObservation.observed_at),
            func.max(WeatherObservation.observed_at),
            func.max(WeatherObservation.fetched_at),
        )
    ).one()
    return ObservationRange(
        first=_iso_z(first) if first else None,
        last=_iso_z(last) if last else None,
        updated_at=_iso_z(updated) if updated else None,
    )


# ---------- READ: самое свежее наблюдение (последняя запись, не позже текущего часа) ----------
@observation_router.get("/latest/{location_id}", response_model=WeatherObservation)
def retrieve_latest_observation(location_id: uuid.UUID,
                                session: Session = Depends(get_session)) -> WeatherObservation:
    now = utc_now().replace(minute=0, second=0, microsecond=0)
    statement = (
        select(WeatherObservation)
        .where(WeatherObservation.location_id == location_id)
        .where(WeatherObservation.observed_at <= now)
        .order_by(col(WeatherObservation.observed_at).desc())
    )
    observation = session.exec(statement).first()
    if observation:
        return observation
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No observations for supplied location"
    )


# ---------- CREATE (ручной ввод) ----------
@observation_router.post("/new")
def create_observation(data: ObservationCreate,
                       session: Session = Depends(get_session)) -> dict:
    if session.get(Location, data.location_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location with supplied ID does not exist"
        )
    values = data.model_dump()
    values["observed_at"] = _naive_utc(values["observed_at"])
    if values.get("weather_condition") is None:
        values["weather_condition"] = describe_weather_code(values.get("weather_code"))
    observation = WeatherObservation(
        **values, source_id=manual_source(session).id, is_forecast=False, fetched_at=utc_now()
    )
    session.add(observation)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Observation for this location, time and source already exists"
        )
    session.refresh(observation)
    return {
        "message": "Observation created successfully",
        "id": str(observation.id)
    }
