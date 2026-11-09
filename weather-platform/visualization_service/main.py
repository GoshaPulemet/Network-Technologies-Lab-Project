from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from clients.data_service import DataServiceClient
from config import STATIC_DIR, settings
from routes.api import api_router
from services.frames import FrameService


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = DataServiceClient()
    app.state.frames = FrameService(client)
    yield
    client.close()


app = FastAPI(
    title="Visualization Service",
    description="Карта погоды по Республике Башкортостан. Данные берёт из weather_data_service "
                f"({settings.data_service_url}). Время в API - UTC.",
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health", tags=["Meta"])
async def health() -> dict:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=True)
