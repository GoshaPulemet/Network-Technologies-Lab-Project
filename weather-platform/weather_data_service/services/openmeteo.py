"""Клиент Open-Meteo (https://open-meteo.com): прогноз и архив (ERA5) для списка точек."""
import time
from datetime import date
from typing import Callable, List, Optional, Sequence, Tuple

from services.parameters import PARAMETERS
from services.parsing import parse_hourly, split_locations_payload

try:  # httpx нужен только для реальных запросов
    import httpx
    _TRANSPORT_ERRORS: tuple = (httpx.TransportError,)
except ImportError:  # pragma: no cover
    httpx = None
    _TRANSPORT_ERRORS = ()

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

Coords = Sequence[Tuple[float, float]]


class OpenMeteoError(RuntimeError):
    pass


def _reason(resp) -> str:
    try:
        return str(resp.json().get("reason", resp.text[:200]))
    except Exception:
        return resp.text[:200]


class OpenMeteoClient:
    def __init__(self, http=None, retries: int = 3, backoff: float = 2.0,
                 timeout: float = 60.0, sleep: Callable[[float], None] = time.sleep):
        self._owns_http = http is None
        if http is None:
            if httpx is None:
                raise RuntimeError("Установите httpx: pip install httpx")
            http = httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0), 
                                                      headers={"User-Agent": "weather-platform-student-project"})
        self._http = http
        self.retries = retries
        self.backoff = backoff
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    # ---------- публичные методы ----------
    def fetch_forecast(self, coords: Coords, forecast_days: int, past_days: int = 0) -> List[List[dict]]:
        """Почасовой прогноз для списка точек. Результат: по списку строк на каждую точку."""
        params = self._base_params(coords)
        params["forecast_days"] = forecast_days
        if past_days:
            params["past_days"] = past_days
        return self._request(FORECAST_URL, params, len(coords))

    def fetch_archive(self, coords: Coords, start: date, end: date) -> List[List[dict]]:
        """Почасовой архив (реанализ ERA5) за период [start, end]."""
        params = self._base_params(coords)
        params["start_date"] = start.isoformat()
        params["end_date"] = end.isoformat()
        return self._request(ARCHIVE_URL, params, len(coords))

    # ---------- внутреннее ----------
    @staticmethod
    def _base_params(coords: Coords) -> dict:
        hourly = [p.api_name for p in PARAMETERS.values()] + ["weather_code"]
        return {
            "latitude": ",".join(f"{lat:.4f}" for lat, _ in coords),
            "longitude": ",".join(f"{lon:.4f}" for _, lon in coords),
            "hourly": ",".join(hourly),
            "timezone": "UTC",
            "wind_speed_unit": "ms",
        }

    def _request(self, url: str, params: dict, expected: int) -> List[List[dict]]:
        payload = self._get(url, params)
        try:
            items = split_locations_payload(payload, expected)
            return [parse_hourly(item) for item in items]
        except ValueError as exc:
            raise OpenMeteoError(str(exc)) from exc

    def _get(self, url: str, params: dict):
        last_error: Optional[str] = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self._http.get(url, params=params)
            except _TRANSPORT_ERRORS as exc:
                last_error = f"сетевая ошибка: {exc}"
            else:
                if resp.status_code == 200:
                    return resp.json()
                reason = _reason(resp)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_error = f"HTTP {resp.status_code}: {reason}"
                else:  # остальные 4xx повторять бессмысленно
                    raise OpenMeteoError(f"HTTP {resp.status_code}: {reason}")
            if attempt < self.retries:
                self._sleep(self.backoff * 2 ** (attempt - 1))
        raise OpenMeteoError(last_error or "неизвестная ошибка")
