import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from database.connections import get_session
from models.weather import Location, LocationUpdate

location_router = APIRouter(
    tags=["Locations"]
)


# ---------- READ: список всех населённых пунктов ----------
@location_router.get("/", response_model=List[Location])
def retrieve_all_locations(session: Session = Depends(get_session)) -> List[Location]:
    return session.exec(select(Location)).all()


# ---------- READ: один населённый пункт ----------
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
def create_location(new_location: Location,
                    session: Session = Depends(get_session)) -> dict:
    session.add(new_location)
    session.commit()
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
    if location:
        for key, value in new_data.model_dump(exclude_unset=True).items():
            setattr(location, key, value)
        session.add(location)
        session.commit()
        session.refresh(location)
        return location
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Location with supplied ID does not exist"
    )


# ---------- DELETE ----------
@location_router.delete("/delete/{location_id}")
def delete_location(location_id: uuid.UUID,
                    session: Session = Depends(get_session)) -> dict:
    location = session.get(Location, location_id)
    if location:
        session.delete(location)
        session.commit()
        return {"message": "Location deleted successfully"}
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Location with supplied ID does not exist"
    )
