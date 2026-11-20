"""Разбор ответа Open-Meteo. Чистые функции без сети и БД."""
from datetime import datetime, timezone
from typing import Any, Dict, List

from services.parameters import PARAMETERS
from services.wmo import describe_weather_code


def parse_time(text: str) -> datetime:
    """'2026-11-06T12:00' -> naive datetime в UTC (мы запрашиваем timezone=UTC)."""
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _convert(value, param):
    if value is None:
        return None
    try:
        return round(float(value) * param.factor, param.decimals)
    except (TypeError, ValueError):
        return None


def parse_hourly(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Ответ для одной точки -> список почасовых строк в наших единицах."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time")
    if not times:
        raise ValueError("В ответе Open-Meteo нет блока hourly.time")

    weather_codes = hourly.get("weather_code") or []
    rows: List[Dict[str, Any]] = []
    for i, t in enumerate(times):
        row: Dict[str, Any] = {"observed_at": parse_time(t)}
        for code, param in PARAMETERS.items():
            series = hourly.get(param.api_name)
            row[code] = _convert(series[i], param) if series and i < len(series) else None
        raw_code = weather_codes[i] if i < len(weather_codes) else None
        row["weather_code"] = int(raw_code) if raw_code is not None else None
        row["weather_condition"] = describe_weather_code(row["weather_code"])
        rows.append(row)
    return rows


def split_locations_payload(payload: Any, expected: int) -> List[Dict[str, Any]]:
    """Для одной точки Open-Meteo возвращает объект, для нескольких - список."""
    if isinstance(payload, dict):
        if payload.get("error"):
            raise ValueError(payload.get("reason", "Open-Meteo вернул ошибку"))
        items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        raise ValueError("Неожиданный формат ответа Open-Meteo")
    if len(items) != expected:
        raise ValueError(f"Запрошено точек: {expected}, в ответе: {len(items)}")
    return items
