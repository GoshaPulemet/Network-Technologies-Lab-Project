"""Настройки сервиса. Любое значение можно переопределить переменной окружения."""
import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


@dataclass(frozen=True)
class Settings:
    data_service_url: str    # где живёт weather_data_service
    data_timeout: float      # таймаут запросов к нему, сек
    tile_url: str            # подложка карты ({z}/{x}/{y}); пусто - карта без подложки
    tile_attribution: str
    utc_offset_hours: float  # часовой пояс отображения (РБ - UTC+5, без перехода на летнее время)
    raster_width: int        # ширина PNG-слоя в пикселях
    cache_ttl: float         # сколько секунд хранить готовый кадр
    cache_size: int          # сколько кадров держать в памяти

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_service_url=os.getenv("DATA_SERVICE_URL", "http://localhost:8003").rstrip("/"),
            data_timeout=float(os.getenv("DATA_TIMEOUT", "15")),
            tile_url=os.getenv(
                "TILE_URL",
                "https://basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png",
            ),
            tile_attribution=os.getenv(
                "TILE_ATTRIBUTION",
                "© OpenStreetMap contributors © CARTO",
            ),
            utc_offset_hours=float(os.getenv("UTC_OFFSET_HOURS", "5")),
            raster_width=int(os.getenv("RASTER_WIDTH", "1100")),
            cache_ttl=float(os.getenv("CACHE_TTL", "600")),
            cache_size=int(os.getenv("CACHE_SIZE", "200")),
        )


settings = Settings.from_env()
