import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from src.util import database
from src.services.profiles import AccountDeletedError
from src.util.auth import not_signed_in
from src.util.database import FplDataUnavailableError
from src.util.fpl_client import FplUnavailableError
from src.middleware.cache import never_cache_accounts
from src.routers import routers

logger = logging.getLogger(__name__)

# Data comes from Postgres, kept current by the hourly sync job, so nothing is
# fetched from FPL at startup.
app = FastAPI(title="Fpl API")

UNAVAILABLE = {"detail": "FPL data is currently unavailable"}

app.middleware("http")(never_cache_accounts)


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


@app.exception_handler(AccountDeletedError)
async def account_deleted_handler(
    _request: Request, _exc: AccountDeletedError
) -> JSONResponse:
    """A deleted account's token still verifies until it expires; refuse it like any
    bad token, so the app treats it as signed out."""
    refused = not_signed_in()
    return JSONResponse(
        status_code=refused.status_code,
        content={"detail": refused.detail},
        headers=refused.headers,
    )


@app.exception_handler(FplUnavailableError)
async def fpl_unavailable_handler(
    _request: Request, _exc: FplUnavailableError
) -> JSONResponse:
    """Return 503 when a live call to FPL fails. Never cached, so the next request
    retries.

    The detail differs from the sync's "FPL data is currently unavailable", so the
    logs and the app can tell the two apart.
    """
    return JSONResponse(
        status_code=503,
        content={"detail": "FPL is unavailable right now"},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/healthcheck", include_in_schema=False)
async def healthcheck() -> dict[str, Optional[str]]:
    """Report that the process is up, whether the database is reachable, and when
    FPL data was last synced (null if never, or if it can't be read).

    last_sync is the bootstrap sync, hourly. last_points_sync is the last gameweek
    whose points were stored, so it only moves when a gameweek is confirmed: about
    weekly, a day or two after the gameweek's last match.

    Always 200, so a database outage doesn't make a host restart the app.
    """
    reachable = await asyncio.to_thread(database.is_database_reachable)
    last_sync = last_points_sync = None
    if reachable:
        last_sync = await asyncio.to_thread(database.get_last_sync)
        last_points_sync = await asyncio.to_thread(
            database.get_last_sync, "event_points"
        )
    return {
        "status": "ok",
        "database": "ok" if reachable else "unavailable",
        "last_sync": last_sync.isoformat() if last_sync else None,
        "last_points_sync": last_points_sync.isoformat() if last_points_sync else None,
    }


app_router = APIRouter(prefix="/api")
app_router.include_router(routers)
app.include_router(app_router)
