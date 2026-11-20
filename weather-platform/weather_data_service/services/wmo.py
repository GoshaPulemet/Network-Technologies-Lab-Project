"""Коды погоды WMO (weather_code в Open-Meteo) -> короткий идентификатор состояния."""
from typing import Optional

_WMO = {
    0: "clear",
    1: "mainly_clear",
    2: "partly_cloudy",
    3: "overcast",
    45: "fog",
    48: "rime_fog",
    51: "drizzle_light",
    53: "drizzle",
    55: "drizzle_dense",
    56: "freezing_drizzle",
    57: "freezing_drizzle",
    61: "rain_light",
    63: "rain",
    65: "rain_heavy",
    66: "freezing_rain",
    67: "freezing_rain",
    71: "snow_light",
    73: "snow",
    75: "snow_heavy",
    77: "snow_grains",
    80: "rain_showers",
    81: "rain_showers",
    82: "rain_showers_heavy",
    85: "snow_showers",
    86: "snow_showers_heavy",
    95: "thunderstorm",
    96: "thunderstorm_hail",
    99: "thunderstorm_hail",
}


def describe_weather_code(code: Optional[int]) -> Optional[str]:
    if code is None:
        return None
    return _WMO.get(int(code), f"code_{int(code)}")
