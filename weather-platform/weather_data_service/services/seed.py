"""Первичное наполнение БД: города РБ и узлы регулярной сетки внутри границы."""
import json
from typing import Dict

from sqlmodel import Session, delete, select

from config import DATA_DIR
from models.weather import Location, WeatherObservation
from services.grid import generate_grid, get_boundary
from services.sources import manual_source, open_meteo_source


def _key(kind: str, lat: float, lon: float) -> tuple:
    return kind, round(lat, 4), round(lon, 4)


def seed_locations(session: Session, step: float) -> Dict[str, object]:
    """Идемпотентно добавляет города и узлы сетки. Возвращает сводку."""
    open_meteo_source(session)
    manual_source(session)

    existing = {
        _key(loc.kind, loc.latitude, loc.longitude)
        for loc in session.exec(select(Location)).all()
    }

    cities_added = 0
    cities = json.loads((DATA_DIR / "cities.json").read_text(encoding="utf-8"))
    for c in cities:
        k = _key("city", c["lat"], c["lon"])
        if k in existing:
            continue
        session.add(Location(name=c["name"], kind="city", district=c.get("district"),
                             latitude=round(c["lat"], 4), longitude=round(c["lon"], 4)))
        existing.add(k)
        cities_added += 1

    polygons, boundary_source = get_boundary()
    grid_added = 0
    for lat, lon in generate_grid(step, list(polygons)):
        k = _key("grid", lat, lon)
        if k in existing:
            continue
        session.add(Location(name=f"Узел {lat:.2f}°N {lon:.2f}°E", kind="grid",
                             latitude=lat, longitude=lon))
        existing.add(k)
        grid_added += 1

    session.commit()
    return {
        "cities_added": cities_added,
        "grid_added": grid_added,
        "grid_step": step,
        "boundary": boundary_source,
    }


def delete_locations_by_kind(session: Session, kind: str) -> int:
    """Удаляет локации заданного типа вместе с их наблюдениями (например, чтобы пересоздать сетку)."""
    count = len(session.exec(select(Location.id).where(Location.kind == kind)).all())
    if not count:
        return 0
    of_kind = select(Location.id).where(Location.kind == kind)
    session.exec(delete(WeatherObservation).where(WeatherObservation.location_id.in_(of_kind)))
    session.exec(delete(Location).where(Location.kind == kind))
    session.commit()
    return count
