from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
import uvicorn

from database.connections import conn
from routes.users import user_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn()
    yield


app = FastAPI(title="User Service", lifespan=lifespan)

app.include_router(user_router, prefix="/user")


@app.get("/", include_in_schema=False)
async def home():
    return RedirectResponse(url="/docs")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)