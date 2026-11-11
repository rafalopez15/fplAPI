from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from src.models.manager import (
    HistoryResponse,
    ManagerResponse,
    PicksResponse,
    TransferResponse,
)
from src.routers.live import Live, LiveRoute
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

MANAGER = LiveRoute(ManagerResponse, MANAGER_CACHE)
TRANSFERS = LiveRoute(List[TransferResponse], TRANSFERS_CACHE)
HISTORY = LiveRoute(HistoryResponse, HISTORY_CACHE)
PICKS = LiveRoute(PicksResponse, PICKS_CACHE)


def manager_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Manager not found", headers=NO_STORE)


@managers_router.get("/managers/{manager_id}")
def get_manager(manager_id: ManagerId, live: Live) -> ManagerResponse:
    """Get a manager's FPL team: team name, points, rank and team value. Never the
    manager's real name.

    The id is the number in the URL of the team's Points page on the FPL site.
    Returns 404 if FPL has no such manager. If FPL can't be reached, returns the
    last copy saved, with X-Data-Stale-As-Of, or 503 without one.
    """
    try:
        return live.call(
            f"managers/{manager_id}",
            MANAGER,
            lambda: managers.get_manager(manager_id),
        )
    except FplNotFoundError as exc:
        raise manager_not_found() from exc


@managers_router.get("/managers/{manager_id}/transfers")
def get_transfers(
    manager_id: ManagerId,
    live: Live,
    session: Annotated[Session, Depends(get_session)],
) -> List[TransferResponse]:
    """List a manager's transfers this season, newest first, with net points.

    Rows with is_churn are swaps undone in the same gameweek (e.g. while planning a
    Wildcard); hide them to list only real transfers. Uses a plain session, not
    DataSession, so the list still loads (with null points) when the database is
    down. Returns 404 if FPL has no such manager. If FPL can't be reached, returns
    the last copy saved, with X-Data-Stale-As-Of, or 503 without one.
    """
    try:
        return live.call(
            f"managers/{manager_id}/transfers",
            TRANSFERS,
            lambda: managers.get_transfers(manager_id, session),
        )
    except FplNotFoundError as exc:
        raise manager_not_found() from exc


@managers_router.get("/managers/{manager_id}/history")
def get_history(manager_id: ManagerId, live: Live) -> HistoryResponse:
    """Get a manager's points and rank per gameweek, chips played and past seasons.

    Returns 404 if FPL has no such manager. If FPL can't be reached, returns the
    last copy saved, with X-Data-Stale-As-Of, or 503 without one.
    """
    try:
        return live.call(
            f"managers/{manager_id}/history",
            HISTORY,
            lambda: managers.get_history(manager_id),
        )
    except FplNotFoundError as exc:
        raise manager_not_found() from exc


@managers_router.get("/managers/{manager_id}/picks")
def get_picks(
    manager_id: ManagerId,
    live: Live,
    event: Annotated[Optional[int], Query(gt=0, description="The gameweek")] = None,
) -> PicksResponse:
    """Get a manager's 15-player squad for a gameweek, with captain, chip and points.

    Without event, returns the manager's current gameweek: the latest one whose
    deadline has passed. FPL only publishes picks after the deadline, so transfers
    made since then don't show yet.
    Returns 404 if FPL has no such manager or no picks for that gameweek. If FPL
    can't be reached, returns the last copy saved, with X-Data-Stale-As-Of, or 503
    without one.
    """
    try:
        result = live.call(
            f"managers/{manager_id}/picks/{event or 'current'}",
            PICKS,
            lambda: managers.get_picks(manager_id, event),
        )
    except FplNotFoundError as exc:
        raise manager_not_found() from exc
    if result is None:
        raise manager_not_found()
    return result
