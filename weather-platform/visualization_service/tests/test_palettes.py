"""Палитры режимов: целостность настроек (опечатка в палитре ломает карту молча)."""
import re

import pytest

from services.palettes import DEFAULT_MODE, HPA_TO_MMHG, MODES, hex_to_rgb

# параметры, которые реально умеет отдавать weather_data_service
DATA_SERVICE_PARAMETERS = {
    "temperature", "humidity", "pressure", "wind_speed", "wind_direction",
    "precipitation", "snow_depth", "cloud_cover",
}


@pytest.mark.parametrize("code", list(MODES))
def test_mode_is_well_formed(code):
    mode = MODES[code]
    assert mode.code == code
    assert mode.parameter in DATA_SERVICE_PARAMETERS
    assert len(mode.stops) >= 2
    values = [s[0] for s in mode.stops]
    assert values == sorted(values) and len(set(values)) == len(values)   # строго по возрастанию
    for _, color, alpha in mode.stops:
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", color)
        assert 0.0 <= alpha <= 1.0


def test_default_mode_exists():
    assert DEFAULT_MODE in MODES


def test_modes_with_hint_have_threshold():
    for mode in MODES.values():
        if mode.empty_hint:
            assert mode.empty_below > 0


def test_only_pressure_is_converted():
    assert MODES["pressure"].factor == HPA_TO_MMHG
    assert all(m.factor == 1.0 for code, m in MODES.items() if code != "pressure")
    assert 1013.25 * HPA_TO_MMHG == pytest.approx(760, abs=0.1)     # стандартная атмосфера


def test_legend_positions_are_evenly_spaced():
    legend = MODES["wind"].legend()                 # у ветра шаги неравные: 3,3,3,3,3,5
    n = len(MODES["wind"].stops)
    assert legend["unit"] == "м/с"
    assert [t["pos"] for t in legend["ticks"]] == [pytest.approx(i / (n - 1)) for i in range(n)]
    assert legend["ticks"][0]["pos"] == 0 and legend["ticks"][-1]["pos"] == 1
    assert [t["value"] for t in legend["ticks"]] == [s[0] for s in MODES["wind"].stops]
    assert [c["color"] for c in legend["colors"]] == [s[1] for s in MODES["wind"].stops]


def test_hex_to_rgb():
    assert hex_to_rgb("#000000") == (0, 0, 0)
    assert hex_to_rgb("#ffffff") == (255, 255, 255)
    assert hex_to_rgb("#4fa65a") == (79, 166, 90)
    assert hex_to_rgb("ff0000") == (255, 0, 0)       # без '#' тоже работает
