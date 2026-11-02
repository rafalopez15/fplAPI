import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from src.util import database
from src.util.database import FplDataUnavailableError
from src.routers import routers

logger = logging.getLogger(__name__)

# Data comes from Postgres, kept current by the hourly sync job, so nothing is
# fetched from FPL at startup.
app = FastAPI(title="Fpl API")

UNAVAILABLE = {"detail": "FPL data is currently unavailable"}


@app.exception_handler(FplDataUnavailableError)
async def fpl_data_unavailable_handler(
    _request: Request, _exc: FplDataUnavailableError
) -> JSONResponse:
    """Return 503 before the first sync, so callers can tell it apart from a 404."""
    return JSONResponse(status_code=503, content=UNAVAILABLE)


@app.exception_handler(OperationalError)
async def database_unavailable_handler(
    _request: Request, exc: OperationalError
) -> JSONResponse:
    """Return 503 when the database can't be reached."""
    logger.warning("Database unavailable: %s", exc.orig)
    return JSONResponse(status_code=503, content=UNAVAILABLE)


@app.get("/healthcheck", include_in_schema=False)
async def healthcheck() -> dict[str, Optional[str]]:
    """Report that the process is up, whether the database is reachable, and when
    FPL data was last synced (null if never, or if it can't be read).

    Always 200, so a database outage doesn't make a host restart the app.
    """
    reachable = await asyncio.to_thread(database.is_database_reachable)
    last_sync = await asyncio.to_thread(database.get_last_sync) if reachable else None
    return {
        "status": "ok",
        "database": "ok" if reachable else "unavailable",
        "last_sync": last_sync.isoformat() if last_sync else None,
    }


app_router = APIRouter(prefix="/api")
app_router.include_router(routers)
app.include_router(app_router)
