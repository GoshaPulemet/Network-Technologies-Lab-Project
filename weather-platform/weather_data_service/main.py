import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from config import settings
from database.connections import conn, engine_url
from models.weather import ImportBatch, Location, utc_now
from routes.locations import location_router
from routes.meta import meta_router
from routes.observations import observation_router
from routes.sync import sync_router
from services.jobs import run_forecast_job
from services.seed import seed_locations
import logging
import threading

_stop = threading.Event()

def _periodic_sync() -> None:
    """Поток daemon: остановка сервиса не ждёт зависший запрос."""
    while not _stop.is_set():
        try:
            run_forecast_job()
        except Exception:
            logging.exception("Автообновление прогноза не удалось")
        _stop.wait(settings.sync_interval_hours * 3600)

def _close_interrupted_batches() -> None:
    with Session(engine_url) as session:
        for b in session.exec(select(ImportBatch).where(ImportBatch.status == "running")):
            b.status = "error"
            b.finished_at = utc_now()
            b.error = "прервано: сервис был остановлен во время загрузки"
            session.add(b)
        session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn()
    _close_interrupted_batches()
    if settings.auto_seed:
        with Session(engine_url) as session:
            if session.exec(select(Location)).first() is None:
                seed_locations(session, settings.grid_step)
    if settings.auto_sync:
        _stop.clear()
        threading.Thread(target=_periodic_sync, daemon=True).start()
    yield
    _stop.set()


app = FastAPI(
    title="Weather Data Service",
    description="Погодные данные по Республике Башкортостан (источник: Open-Meteo). "
                "Время во всех данных - UTC.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(location_router, prefix="/location")
app.include_router(observation_router, prefix="/observation")
app.include_router(sync_router, prefix="/sync")
app.include_router(meta_router, prefix="/meta")


@app.get("/health", tags=["Meta"])
async def health() -> dict:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def home():
    return RedirectResponse(url="/docs")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8003, reload=False)
