from datetime import date
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlmodel import Session, col, select

from database.connections import get_session
from models.weather import ImportBatch
from services.collector import clamp_archive_period
from services.jobs import is_sync_running, run_archive_job, run_forecast_job

sync_router = APIRouter(tags=["Sync"])

MAX_ARCHIVE_DAYS = 400


# ---------- запуск обновления прогноза (в фоне) ----------
@sync_router.post("/forecast", status_code=status.HTTP_202_ACCEPTED)
def trigger_forecast_sync(background: BackgroundTasks) -> dict:
    if is_sync_running():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Another sync is already running")
    background.add_task(run_forecast_job)
    return {"message": "Forecast sync started. Progress: GET /sync/batches"}


# ---------- запуск загрузки архива за период (в фоне) ----------
@sync_router.post("/archive", status_code=status.HTTP_202_ACCEPTED)
def trigger_archive_sync(date_from: date, date_to: date, background: BackgroundTasks) -> dict:
    if date_from > date_to:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="date_from must not be after date_to")
    if (date_to - date_from).days > MAX_ARCHIVE_DAYS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Period is limited to {MAX_ARCHIVE_DAYS} days per request")
    try:
        clamp_archive_period(date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if is_sync_running():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Another sync is already running")
    background.add_task(run_archive_job, date_from, date_to)
    return {"message": "Archive sync started. Progress: GET /sync/batches"}


# ---------- журнал загрузок ----------
@sync_router.get("/batches", response_model=List[ImportBatch])
def retrieve_batches(limit: int = Query(default=20, ge=1, le=100),
                     session: Session = Depends(get_session)) -> List[ImportBatch]:
    statement = select(ImportBatch).order_by(col(ImportBatch.started_at).desc()).limit(limit)
    return session.exec(statement).all()
