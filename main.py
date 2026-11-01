import asyncio
from contextlib import asynccontextmanager
import logging
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from src.util import database
from src.util.fpl_service import FplDataUnavailableError, FplService
from src.routers import routers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Load FPL data once at startup.

    If the fetch fails, the app still starts. Data endpoints return 503 until
    /events/current-event/ refreshes the data or the app restarts.
    """
    await FplService().get_fpl_api_data()
    yield


app = FastAPI(title="Fpl API", lifespan=lifespan)


@app.exception_handler(FplDataUnavailableError)
async def fpl_data_unavailable_handler(
    _request: Request, _exc: FplDataUnavailableError
) -> JSONResponse:
    """Return 503 when FPL data hasn't loaded, so callers can tell it apart from a 404."""
    return JSONResponse(
        status_code=503, content={"detail": "FPL data is currently unavailable"}
    )


@app.get("/healthcheck", include_in_schema=False)
async def healthcheck() -> dict[str, str]:
    """Report that the process is up and whether the database is reachable.

    Always 200, so a database outage doesn't make a host restart the app. This
    doesn't check whether FPL data is loaded.
    """
    reachable = await asyncio.to_thread(database.is_database_reachable)
    return {"status": "ok", "database": "ok" if reachable else "unavailable"}


app_router = APIRouter(prefix="/api")
app_router.include_router(routers)
app.include_router(app_router)
