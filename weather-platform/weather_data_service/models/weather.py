import uuid
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import NaiveDatetime

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    """Текущее время UTC без tzinfo: во всей БД время хранится как naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# =====================================================================
#  Таблицы
# =====================================================================
class DataSource(SQLModel, table=True):
    """Откуда пришли данные (Open-Meteo, ручной ввод ...)."""
    __tablename__ = "data_sources"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(unique=True, index=True)
    name: str
    url: Optional[str] = None
    license: Optional[str] = None


class Location(SQLModel, table=True):
    """Точка, для которой хранится погода: город ('city') или узел сетки ('grid')."""
    __tablename__ = "locations"
    __table_args__ = (UniqueConstraint("kind", "latitude", "longitude", name="uq_location_kind_coords"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    kind: str = Field(default="city", index=True)
    country: str = "RU"
    region: Optional[str] = "Республика Башкортостан"
    district: Optional[str] = None
    latitude: float
    longitude: float


class WeatherObservation(SQLModel, table=True):
    """Почасовое значение погоды для точки. observed_at - момент, к которому относится значение (UTC)."""
    __tablename__ = "weather_observation"
    __table_args__ = (
        UniqueConstraint("location_id", "observed_at", "source_id", name="uq_obs_location_time_source"),
        Index("ix_obs_location_time", "location_id", "observed_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    location_id: uuid.UUID = Field(foreign_key="locations.id")
    source_id: uuid.UUID = Field(foreign_key="data_sources.id")
    observed_at: NaiveDatetime = Field(index=True)
    is_forecast: bool = False
    fetched_at: Optional[NaiveDatetime] = None

    temperature: Optional[float] = None       # °C
    humidity: Optional[float] = None          # %
    pressure: Optional[float] = None          # гПа (приведено к уровню моря)
    wind_speed: Optional[float] = None        # м/с
    wind_direction: Optional[float] = None    # градусы
    precipitation: Optional[float] = None     # мм за час
    snow_depth: Optional[float] = None        # см
    cloud_cover: Optional[float] = None       # %
    weather_code: Optional[int] = None        # код WMO
    weather_condition: Optional[str] = None


class ImportBatch(SQLModel, table=True):
    """Журнал загрузок данных из внешних API."""
    __tablename__ = "import_batches"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source_id: uuid.UUID = Field(foreign_key="data_sources.id")
    kind: str                                   # 'forecast' | 'archive'
    status: str = "running"                     # running | ok | partial | error
    started_at: NaiveDatetime = Field(default_factory=utc_now)
    finished_at: Optional[NaiveDatetime] = None
    locations_total: int = 0
    rows_upserted: int = 0
    period_from: Optional[NaiveDatetime] = None
    period_to: Optional[NaiveDatetime] = None
    error: Optional[str] = None


# =====================================================================
#  Схемы запросов и ответов (не таблицы)
# =====================================================================
class LocationCreate(SQLModel):
    name: str = Field(min_length=1)
    kind: str = "city"
    district: Optional[str] = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    model_config = {
        "json_schema_extra": {
            "example": {"name": "Уфа", "kind": "city", "latitude": 54.7388, "longitude": 55.9721}
        }
    }


class LocationUpdate(SQLModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    district: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


class ObservationCreate(SQLModel):
    """Ручное добавление наблюдения (источник 'manual')."""
    location_id: uuid.UUID
    observed_at: datetime
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    pressure: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_direction: Optional[float] = None
    precipitation: Optional[float] = None
    snow_depth: Optional[float] = None
    cloud_cover: Optional[float] = None
    weather_code: Optional[int] = None
    weather_condition: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "location_id": "00000000-0000-0000-0000-000000000000",
                "observed_at": "2026-11-06T12:00:00",
                "temperature": 3.5,
                "humidity": 80,
                "pressure": 1008,
                "wind_speed": 4.2,
                "wind_direction": 180,
                "precipitation": 0.0,
                "snow_depth": 0,
                "cloud_cover": 60,
            }
        }
    }


class NearestLocation(SQLModel):
    id: uuid.UUID
    name: str
    kind: str
    latitude: float
    longitude: float
    distance_km: float


class SnapshotPoint(SQLModel):
    location_id: uuid.UUID
    name: str
    latitude: float
    longitude: float
    value: float


class Snapshot(SQLModel):
    """Значения одного параметра во всех точках на один момент - основа для карты."""
    parameter: str
    unit: str
    at: str                      # ISO 8601, UTC, с суффиксом Z
    count: int
    points: List[SnapshotPoint]


class SeriesPoint(SQLModel):
    t: str                       # ISO 8601, UTC, с суффиксом Z
    value: Optional[float] = None


class Series(SQLModel):
    location_id: uuid.UUID
    parameter: str
    unit: str
    points: List[SeriesPoint]


class ObservationRange(SQLModel):
    first: Optional[str] = None  # самый ранний момент в БД (ISO, UTC, Z)
    last: Optional[str] = None   # самый поздний момент (конец прогноза)
    updated_at: Optional[str] = None  # когда последний раз загружали данные
