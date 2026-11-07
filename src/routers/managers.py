from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from src.models.manager import (
    HistoryResponse,
    ManagerResponse,
    PicksResponse,
    TransferResponse,
)
from src.routers.params import ManagerId
from src.services import managers
from src.util.database import get_session
from src.util.fpl_client import FplNotFoundError

managers_router = APIRouter()

# Vercel's CDN caches successful responses for s-maxage seconds, shared by every
# user, then serves the old copy for up to stale-while-revalidate seconds while it
# refreshes in the background. Errors are never cached.
MANAGER_CACHE = "s-maxage=60, stale-while-revalidate=300"
TRANSFERS_CACHE = "s-maxage=60, stale-while-revalidate=60"
HISTORY_CACHE = "s-maxage=300, stale-while-revalidate=600"
PICKS_CACHE = "s-maxage=60, stale-while-revalidate=300"
NO_STORE = {"Cache-Control": "no-store"}


def manager_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Manager not found", headers=NO_STORE)


@managers_router.get("/managers/{manager_id}")
def get_manager(manager_id: ManagerId, response: Response) -> ManagerResponse:
    """Get a manager's FPL team: team name, points, rank and team value. Never the
    manager's real name.

    The id is the number in the URL of the team's Points page on the FPL site.
    Returns 404 if FPL has no such manager, and 503 if FPL can't be reached.
    """
    try:
        result = managers.get_manager(manager_id)
    except FplNotFoundError as exc:
        raise manager_not_found() from exc
    response.headers["Cache-Control"] = MANAGER_CACHE
    return result


@managers_router.get("/managers/{manager_id}/transfers")
def get_transfers(
    manager_id: ManagerId,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> List[TransferResponse]:
    """List a manager's transfers this season, newest first, with net points.

    Rows with is_churn are swaps undone in the same gameweek (e.g. while planning a
    Wildcard); hide them to list only real transfers. Uses a plain session, not
    DataSession, so the list still loads (with null points) when the database is
    down. Returns 404 if FPL has no such manager, and 503 if FPL can't be reached.
    """
    try:
        result = managers.get_transfers(manager_id, session)
    except FplNotFoundError as exc:
        raise manager_not_found() from exc
    response.headers["Cache-Control"] = TRANSFERS_CACHE
    return result


@managers_router.get("/managers/{manager_id}/history")
def get_history(manager_id: ManagerId, response: Response) -> HistoryResponse:
    """Get a manager's points and rank per gameweek, chips played and past seasons.

    Returns 404 if FPL has no such manager, and 503 if FPL can't be reached.
    """
    try:
        result = managers.get_history(manager_id)
    except FplNotFoundError as exc:
        raise manager_not_found() from exc
    response.headers["Cache-Control"] = HISTORY_CACHE
    return result


@managers_router.get("/managers/{manager_id}/picks")
def get_picks(
    manager_id: ManagerId,
    response: Response,
    event: Annotated[Optional[int], Query(gt=0, description="The gameweek")] = None,
) -> PicksResponse:
    """Get a manager's 15-player squad for a gameweek, with captain, chip and points.

    Without event, returns the manager's current gameweek: the latest one whose
    deadline has passed. FPL only publishes picks after the deadline, so transfers
    made since then don't show yet.
    Returns 404 if FPL has no such manager or no picks for that gameweek, and 503 if
    FPL can't be reached.
    """
    try:
        result = managers.get_picks(manager_id, event)
    except FplNotFoundError as exc:
        raise manager_not_found() from exc
    if result is None:
        raise manager_not_found()
    response.headers["Cache-Control"] = PICKS_CACHE
    return result
