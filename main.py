from contextlib import asynccontextmanager
import logging
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from src.util.fpl_service import FplDataUnavailableError, FplService
from src.routers import routers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await FplService().get_fpl_api_data()
    yield


app = FastAPI(title="Fpl API", lifespan=lifespan)


@app.exception_handler(FplDataUnavailableError)
async def fpl_data_unavailable_handler(
    request: Request, exc: FplDataUnavailableError
) -> JSONResponse:
    return JSONResponse(
        status_code=503, content={"detail": "FPL data is currently unavailable"}
    )


@app.get("/healthcheck", include_in_schema=False)
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


app_router = APIRouter(prefix="/api")
app_router.include_router(routers)
app.include_router(app_router)
