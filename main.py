from contextlib import asynccontextmanager
import logging
from fastapi import APIRouter, FastAPI
from src.util.fpl_service import FplService
from src.routers import routers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await FplService().get_fpl_api_data()
    yield


app = FastAPI(title="Fpl API", lifespan=lifespan)


@app.get("/healthcheck", include_in_schema=False)
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


app_router = APIRouter(prefix="/api")
app_router.include_router(routers)
app.include_router(app_router)
