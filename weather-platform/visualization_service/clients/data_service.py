"""Клиент weather_data_service. Визуализация ходит за данными только сюда."""
from datetime import datetime
from typing import Any, List, Optional

import httpx

from config import settings


class DataServiceError(Exception):
    """weather_data_service недоступен или вернул ошибку."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class DataServiceClient:
    def __init__(self, base_url: Optional[str] = None, timeout: Optional[float] = None,
                 transport: Optional[httpx.BaseTransport] = None):
        self._client = httpx.Client(
            base_url=(base_url or settings.data_service_url),
            timeout=timeout or settings.data_timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        try:
            resp = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise DataServiceError(f"weather_data_service недоступен: {exc}") from exc
        if resp.status_code >= 400:
            raise DataServiceError(
                f"weather_data_service вернул {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
            )
        return resp.json()

    # ---- методы под нужды карты ----
    def snapshot(self, parameter: str, at: datetime, kind: str = "grid") -> dict:
        return self._get("/observation/snapshot", parameter=parameter,
                         at=at.replace(microsecond=0).isoformat() + "Z", kind=kind)

    def time_range(self) -> dict:
        return self._get("/observation/range")

    def boundary(self) -> dict:
        return self._get("/meta/boundary")

    def cities(self) -> List[dict]:
        return self._get("/location/", kind="city", limit=1000)
