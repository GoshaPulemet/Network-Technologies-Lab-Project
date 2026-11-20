"""Режимы отображения карты: какой параметр показываем, в каких единицах и какими цветами.

Цвет между опорными точками (stops) интерполируется линейно по значению.
На легенде опорные точки стоят на равных расстояниях - так же, как в Яндекс Погоде,
поэтому шкалы с неравномерными шагами (осадки, снег) остаются читаемыми.
"""
from dataclasses import dataclass
from typing import Dict, List, Tuple

# (значение в единицах отображения, цвет '#rrggbb', непрозрачность слоя 0..1)
Stop = Tuple[float, str, float]

HPA_TO_MMHG = 0.750062


@dataclass(frozen=True)
class Mode:
    code: str            # код режима в URL и в UI
    parameter: str       # параметр в weather_data_service
    label: str           # подпись кнопки
    unit: str            # единица на легенде
    stops: List[Stop]
    factor: float = 1.0  # из единиц БД в единицы отображения
    empty_hint: str = ""  # подсказка, если на карте "пусто" (все значения ниже первой отметки)
    empty_below: float = 0.0

    def legend(self) -> dict:
        n = len(self.stops)
        return {
            "unit": self.unit,
            "ticks": [
                {"value": s[0], "pos": i / (n - 1)} for i, s in enumerate(self.stops)
            ],
            "colors": [
                {"pos": i / (n - 1), "color": s[1]} for i, s in enumerate(self.stops)
            ],
        }


MODES: Dict[str, Mode] = {m.code: m for m in [
    Mode(
        code="precipitation", parameter="precipitation", label="Осадки", unit="мм/ч",
        stops=[
            (0.0, "#5b7a99", 0.0),
            (0.1, "#8fd0ff", 0.55),
            (0.5, "#4a9bff", 0.8),
            (1.0, "#2c5be6", 0.85),
            (2.5, "#7b3fe4", 0.88),
            (5.0, "#c63fd6", 0.9),
            (10.0, "#ff4f9a", 0.92),
        ],
        empty_below=0.1, empty_hint="На выбранный час осадков нет",
    ),
    Mode(
        code="temperature", parameter="temperature", label="Температура", unit="°C",
        stops=[
            (-40, "#2d1b5e", 0.82),
            (-30, "#1d2a9a", 0.82),
            (-20, "#2a4fd0", 0.82),
            (-10, "#2f86c8", 0.82),
            (0, "#35a39b", 0.82),
            (10, "#4fa65a", 0.82),
            (20, "#b0aa2a", 0.82),
            (30, "#c06a22", 0.82),
            (40, "#7d1c1c", 0.82),
        ],
    ),
    Mode(
        code="wind", parameter="wind_speed", label="Ветер", unit="м/с",
        stops=[
            (0, "#3b6fb6", 0.8),
            (3, "#3aa0a8", 0.8),
            (6, "#55b05a", 0.8),
            (9, "#c8c030", 0.82),
            (12, "#e08a2a", 0.84),
            (15, "#d04030", 0.86),
            (20, "#8a2a8a", 0.88),
        ],
    ),
    Mode(
        code="pressure", parameter="pressure", label="Давление", unit="мм рт. ст.",
        factor=HPA_TO_MMHG,
        stops=[
            (730, "#5a2d9c", 0.82),
            (740, "#2f4fc8", 0.82),
            (750, "#2f9ab8", 0.82),
            (760, "#4fa65a", 0.82),
            (770, "#c8b82e", 0.82),
            (780, "#c8552a", 0.82),
        ],
    ),
    Mode(
        code="snow_depth", parameter="snow_depth", label="Глубина снега", unit="см",
        stops=[
            (0, "#9fb4c8", 0.0),
            (1, "#cfe8ff", 0.5),
            (5, "#9fd0ff", 0.72),
            (10, "#6fa8ff", 0.8),
            (20, "#4a78e8", 0.85),
            (40, "#6a4ac8", 0.88),
            (80, "#9a3fb8", 0.9),
        ],
        empty_below=1.0, empty_hint="Снежного покрова на карте нет",
    ),
]}

DEFAULT_MODE = "temperature"


def hex_to_rgb(color: str) -> Tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
