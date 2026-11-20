from typing import List

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from database.connections import get_session
from models.weather import DataSource
from services.grid import get_boundary, polygons_to_geojson
from services.parameters import PARAMETERS

meta_router = APIRouter(tags=["Meta"])


@meta_router.get("/parameters")
def retrieve_parameters() -> List[dict]:
    """Какие параметры есть, их единицы и подписи (для переключателя слоёв)."""
    return [
        {"code": p.code, "label": p.label, "unit": p.unit}
        for p in PARAMETERS.values()
    ]


@meta_router.get("/sources", response_model=List[DataSource])
def retrieve_sources(session: Session = Depends(get_session)) -> List[DataSource]:
    """Источники данных и лицензии (для подписи на сайте)."""
    return session.exec(select(DataSource)).all()


@meta_router.get("/boundary")
def retrieve_boundary() -> dict:
    """Граница РБ в формате GeoJSON (для отрисовки на карте и обрезки слоя)."""
    polygons, source = get_boundary()
    geojson = polygons_to_geojson(list(polygons))
    geojson["features"][0]["properties"]["source"] = source  # 'file' или 'builtin'
    return geojson
