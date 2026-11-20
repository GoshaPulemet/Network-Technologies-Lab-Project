from typing import Optional

from sqlmodel import Session, select

from models.weather import DataSource

OPEN_METEO_CODE = "open-meteo"
MANUAL_CODE = "manual"


def get_or_create_source(session: Session, code: str, name: str,
                         url: Optional[str] = None, license: Optional[str] = None) -> DataSource:
    source = session.exec(select(DataSource).where(DataSource.code == code)).first()
    if source is None:
        source = DataSource(code=code, name=name, url=url, license=license)
        session.add(source)
        session.commit()
        session.refresh(source)
    return source


def open_meteo_source(session: Session) -> DataSource:
    return get_or_create_source(
        session, OPEN_METEO_CODE, "Open-Meteo",
        url="https://open-meteo.com", license="CC BY 4.0 (данные Open-Meteo, реанализ ERA5)",
    )


def manual_source(session: Session) -> DataSource:
    return get_or_create_source(session, MANUAL_CODE, "Ручной ввод")
