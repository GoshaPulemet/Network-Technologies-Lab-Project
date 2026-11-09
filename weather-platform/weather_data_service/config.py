"""Настройки сервиса. Любое значение можно переопределить переменной окружения."""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Прямоугольник вокруг Республики Башкортостан (с небольшим запасом).
# Сервис работает только в его пределах.
RB_LAT_MIN, RB_LAT_MAX = 51.3, 56.8
RB_LON_MIN, RB_LON_MAX = 52.8, 60.4

# Архив ERA5 обновляется с задержкой в несколько дней
ARCHIVE_LAG_DAYS = 5


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    sql_echo: bool
    boundary_file: Path
    grid_step: float            # шаг сетки в градусах
    auto_seed: bool             # создавать локации при старте, если их нет
    auto_sync: bool             # периодически обновлять прогноз в фоне
    sync_interval_hours: float
    forecast_days: int          # на сколько суток вперёд (Open-Meteo: до 16)
    past_days: int              # сколько суток назад добирать вместе с прогнозом
    request_chunk: int          # сколько точек в одном запросе прогноза
    archive_chunk: int          # сколько точек в одном запросе архива
    request_pause: float        # пауза между запросами, сек
    cors_origins: List[str]

    @classmethod
    def from_env(cls) -> "Settings":
        default_db = "sqlite:///" + str(BASE_DIR / "weather_data.db")
        origins = os.getenv("CORS_ORIGINS", "*")
        return cls(
            database_url=os.getenv("DATABASE_URL", default_db),
            sql_echo=_env_bool("SQL_ECHO", False),
            boundary_file=Path(os.getenv("BOUNDARY_FILE", DATA_DIR / "rb_boundary.geojson")),
            grid_step=float(os.getenv("GRID_STEP", "0.25")),
            auto_seed=_env_bool("AUTO_SEED", True),
            auto_sync=_env_bool("AUTO_SYNC", False),
            sync_interval_hours=float(os.getenv("SYNC_INTERVAL_HOURS", "3")),
            forecast_days=int(os.getenv("FORECAST_DAYS", "3")),
            past_days=int(os.getenv("PAST_DAYS", "1")),
            request_chunk=int(os.getenv("REQUEST_CHUNK", "50")),
            archive_chunk=int(os.getenv("ARCHIVE_CHUNK", "10")),
            request_pause=float(os.getenv("REQUEST_PAUSE", "1.0")),
            cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        )


settings = Settings.from_env()
