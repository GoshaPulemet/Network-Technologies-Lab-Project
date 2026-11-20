from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from clients.data_service import DataServiceError
from config import settings
from services.frames import FrameService, NoDataError
from services.palettes import DEFAULT_MODE, MODES

api_router = APIRouter(tags=["Visualization"])


def _frames(request: Request) -> FrameService:
    return request.app.state.frames


def _upstream_error(exc: DataServiceError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


# ---------- всё, что нужно странице для старта ----------
@api_router.get("/config")
def get_config(request: Request) -> dict:
    frames = _frames(request)
    try:
        geometry = frames.frame_geometry()
        boundary = frames.boundary_geojson()
        cities = frames.cities()
        time_range = frames.client.time_range()
    except DataServiceError as exc:
        raise _upstream_error(exc)
    return {
        "modes": [
            {"code": m.code, "label": m.label, "unit": m.unit,
             "legend": m.legend(), "empty_hint": m.empty_hint}
            for m in MODES.values()
        ],
        "default_mode": DEFAULT_MODE,
        "frame": {                          # где положить PNG на карту
            "lat_min": geometry.lat_min, "lat_max": geometry.lat_max,
            "lon_min": geometry.lon_min, "lon_max": geometry.lon_max,
        },
        "boundary": boundary,
        "cities": cities,
        "time_range": time_range,
        "utc_offset_hours": settings.utc_offset_hours,
        "tiles": {"url": settings.tile_url, "attribution": settings.tile_attribution},
    }


# ---------- за какой период есть данные (границы шкалы времени) ----------
@api_router.get("/range")
def get_range(request: Request) -> dict:
    try:
        return _frames(request).client.time_range()
    except DataServiceError as exc:
        raise _upstream_error(exc)


# ---------- кадр: цветной слой для режима и часа ----------
@api_router.get("/frame/{mode}.png", responses={200: {"content": {"image/png": {}}}})
def get_frame(
        mode: str,
        request: Request,
        at: Optional[datetime] = Query(default=None, description="Момент времени, UTC. По умолчанию - текущий час"),
) -> Response:
    if mode not in MODES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown mode '{mode}'. Allowed: {', '.join(MODES)}",
        )
    moment = at or datetime.now(timezone.utc)
    try:
        rendered = _frames(request).render(mode, moment)
    except NoDataError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except DataServiceError as exc:
        raise _upstream_error(exc)

    spec = MODES[mode]
    empty = bool(spec.empty_hint) and rendered.vmax < spec.empty_below
    return Response(
        content=rendered.png,
        media_type="image/png",
        headers={
            "Cache-Control": f"public, max-age={int(settings.cache_ttl)}",
            "X-Value-Min": f"{rendered.vmin:.3f}",
            "X-Value-Max": f"{rendered.vmax:.3f}",
            "X-Empty": "1" if empty else "0",
        },
    )
