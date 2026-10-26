import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from database.connections import get_session
from models.weather import Location, ObservationCreate, WeatherObservation

observation_router = APIRouter(
    tags=["Observations"]
)


# ---------- READ: наблюдения с фильтрами ----------
# limit=N возвращает N самых свежих наблюдений (в порядке возрастания времени)
@observation_router.get("/", response_model=List[WeatherObservation])
def retrieve_observations(
        location_id: Optional[uuid.UUID] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: Optional[int] = Query(default=None, ge=1, le=1000),
        session: Session = Depends(get_session)) -> List[WeatherObservation]:
    statement = select(WeatherObservation)
    if location_id:
        statement = statement.where(WeatherObservation.location_id == location_id)
    if date_from:
        statement = statement.where(WeatherObservation.observed_at >= date_from)
    if date_to:
        statement = statement.where(WeatherObservation.observed_at <= date_to)

    if limit:
        statement = statement.order_by(col(WeatherObservation.observed_at).desc()).limit(limit)
        return list(reversed(session.exec(statement).all()))

    statement = statement.order_by(col(WeatherObservation.observed_at))
    return session.exec(statement).all()


# ---------- READ: самое свежее наблюдение (текущая погода) ----------
@observation_router.get("/latest/{location_id}", response_model=WeatherObservation)
def retrieve_latest_observation(location_id: uuid.UUID,
                                session: Session = Depends(get_session)) -> WeatherObservation:
    statement = (
        select(WeatherObservation)
        .where(WeatherObservation.location_id == location_id)
        .order_by(col(WeatherObservation.observed_at).desc())
    )
    observation = session.exec(statement).first()
    if observation:
        return observation
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No observations for supplied location"
    )


# ---------- CREATE ----------
@observation_router.post("/new")
def create_observation(data: ObservationCreate,
                       session: Session = Depends(get_session)) -> dict:
    if session.get(Location, data.location_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location with supplied ID does not exist"
        )
    observation = WeatherObservation(**data.model_dump())
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
