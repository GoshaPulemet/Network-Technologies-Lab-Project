import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, delete, select

from database.connections import get_session
from models.weather import (
    Location, LocationCreate, LocationUpdate, NearestLocation, WeatherObservation,
)
from services.geo import haversine_km, in_rb_bbox

location_router = APIRouter(tags=["Locations"])

_OUTSIDE = "Координаты вне области Республики Башкортостан"


# ---------- READ: список локаций (kind=city | grid) ----------
@location_router.get("/", response_model=List[Location])
def retrieve_all_locations(
        kind: Optional[str] = None,
        limit: int = Query(default=1000, ge=1, le=5000),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_session)) -> List[Location]:
    statement = select(Location)
    if kind:
        statement = statement.where(Location.kind == kind)
    statement = statement.order_by(col(Location.name)).offset(offset).limit(limit)
    return session.exec(statement).all()


# ---------- READ: ближайшая локация к точке (клик по карте) ----------
# Должен быть объявлен ДО "/{location_id}", иначе "nearest" будет принят за UUID
@location_router.get("/nearest", response_model=NearestLocation)
def retrieve_nearest_location(
        lat: float = Query(..., ge=-90, le=90),
        lon: float = Query(..., ge=-180, le=180),
        kind: Optional[str] = None,
        session: Session = Depends(get_session)) -> NearestLocation:
    if not in_rb_bbox(lat, lon):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_OUTSIDE)
    statement = select(Location)
    if kind:
        statement = statement.where(Location.kind == kind)
    candidates = session.exec(statement).all()
    if not candidates:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Нет локаций")
    best = min(candidates, key=lambda c: haversine_km(lat, lon, c.latitude, c.longitude))
    return NearestLocation(
        id=best.id, name=best.name, kind=best.kind,
        latitude=best.latitude, longitude=best.longitude,
        distance_km=round(haversine_km(lat, lon, best.latitude, best.longitude), 2),
    )


# ---------- READ: одна локация ----------
@location_router.get("/{location_id}", response_model=Location)
def retrieve_location(location_id: uuid.UUID,
                      session: Session = Depends(get_session)) -> Location:
    location = session.get(Location, location_id)
    if location:
        return location
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Location with supplied ID does not exist"
    )


# ---------- CREATE ----------
@location_router.post("/new")
def create_location(data: LocationCreate,
                    session: Session = Depends(get_session)) -> dict:
    if not in_rb_bbox(data.latitude, data.longitude):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_OUTSIDE)
    new_location = Location(**data.model_dump())
    session.add(new_location)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Location with these coordinates already exists"
        )
    session.refresh(new_location)
    return {
        "message": "Location created successfully",
        "id": str(new_location.id)
    }


# ---------- UPDATE ----------
@location_router.put("/edit/{location_id}", response_model=Location)
def update_location(location_id: uuid.UUID, new_data: LocationUpdate,
                    session: Session = Depends(get_session)) -> Location:
    location = session.get(Location, location_id)
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location with supplied ID does not exist"
        )
    changes = new_data.model_dump(exclude_unset=True)
    lat = changes.get("latitude", location.latitude)
    lon = changes.get("longitude", location.longitude)
    if not in_rb_bbox(lat, lon):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_OUTSIDE)
    for key, value in changes.items():
        setattr(location, key, value)
    session.add(location)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Location with these coordinates already exists"
        )
    session.refresh(location)
    return location


# ---------- DELETE (вместе с наблюдениями этой локации) ----------
@location_router.delete("/delete/{location_id}")
def delete_location(location_id: uuid.UUID,
                    session: Session = Depends(get_session)) -> dict:
    location = session.get(Location, location_id)
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Location with supplied ID does not exist"
        )
    session.exec(delete(WeatherObservation).where(WeatherObservation.location_id == location_id))
    session.delete(location)
    session.commit()
    return {"message": "Location deleted successfully"}
