from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
import uvicorn

from database.connections import conn
from routes.locations import location_router
from routes.observations import observation_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn()
    yield


app = FastAPI(title="Weather Data Service", lifespan=lifespan)

app.include_router(location_router, prefix="/location")
app.include_router(observation_router, prefix="/observation")


@app.get("/", include_in_schema=False)
async def home():
    return RedirectResponse(url="/docs")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8003, reload=True)
