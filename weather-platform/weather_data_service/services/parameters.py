"""Реестр погодных параметров: единый источник правды для БД, API и визуализации."""
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class Parameter:
    code: str            # имя колонки в БД и параметр в нашем API
    api_name: str        # имя переменной в Open-Meteo
    label: str           # подпись для интерфейса
    unit: str            # единица, в которой значение хранится в БД
    factor: float = 1.0  # множитель при конвертации из единиц Open-Meteo
    decimals: int = 1


_LIST = [
    Parameter("temperature", "temperature_2m", "Температура", "°C"),
    Parameter("humidity", "relative_humidity_2m", "Влажность", "%", decimals=0),
    Parameter("pressure", "pressure_msl", "Давление", "гПа"),
    Parameter("wind_speed", "wind_speed_10m", "Скорость ветра", "м/с"),
    Parameter("wind_direction", "wind_direction_10m", "Направление ветра", "°", decimals=0),
    Parameter("precipitation", "precipitation", "Осадки", "мм", decimals=2),
    # Open-Meteo отдаёт глубину снега в метрах, храним в сантиметрах (как на легенде карты)
    Parameter("snow_depth", "snow_depth", "Глубина снега", "см", factor=100.0),
    Parameter("cloud_cover", "cloud_cover", "Облачность", "%", decimals=0),
]

PARAMETERS: Dict[str, Parameter] = {p.code: p for p in _LIST}
