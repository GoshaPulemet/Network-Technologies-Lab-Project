import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field


class Location(SQLModel, table=True):
    __tablename__ = "locations"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    country: str
    region: Optional[str] = None
    latitude: float
    longitude: float

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Stockholm",
                "country": "SE",
                "region": "Stockholm",
                "latitude": 59.33,
                "longitude": 18.07,
            }
        }
    }


class LocationUpdate(SQLModel):
    name: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class WeatherObservation(SQLModel, table=True):
    __tablename__ = "weather_observation"
    __table_args__ = (UniqueConstraint("location_id", "observed_at", "source_id"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    location_id: uuid.UUID = Field(foreign_key="locations.id", index=True)
    observed_at: datetime = Field(index=True)
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    pressure: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_direction: Optional[float] = None
    precipitation: Optional[float] = None
    weather_condition: Optional[str] = None
    source_id: Optional[uuid.UUID] = None


class ObservationCreate(SQLModel):
    """Тело запроса POST /observation/new (валидируется до создания записи)."""
    location_id: uuid.UUID
    observed_at: datetime
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    pressure: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_direction: Optional[float] = None
    precipitation: Optional[float] = None
    weather_condition: Optional[str] = None
    source_id: Optional[uuid.UUID] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "location_id": "00000000-0000-0000-0000-000000000000",
                "observed_at": "2026-10-26T12:00:00",
                "temperature": 7.5,
                "humidity": 80.0,
                "pressure": 1008.0,
                "wind_speed": 4.2,
                "wind_direction": 180,
                "precipitation": 0.0,
                "weather_condition": "clear",
            }
        }
    }
