from typing import Annotated, List
from fastapi import APIRouter, HTTPException, Path, Response
from src.models.manager import HistoryResponse, ManagerResponse, TransferResponse
from src.services import managers
from src.util.fpl_client import FplNotFoundError

managers_router = APIRouter()

# Vercel's CDN caches successful responses for s-maxage seconds, shared by every
# user, then serves the old copy for up to stale-while-revalidate seconds while it
# refreshes in the background. Errors are never cached.
MANAGER_CACHE = "s-maxage=60, stale-while-revalidate=300"
TRANSFERS_CACHE = "s-maxage=60, stale-while-revalidate=60"
HISTORY_CACHE = "s-maxage=300, stale-while-revalidate=600"
NO_STORE = {"Cache-Control": "no-store"}

ManagerId = Annotated[int, Path(gt=0, description="The FPL manager (entry) id")]


def manager_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Manager not found", headers=NO_STORE)


@managers_router.get("/managers/{manager_id}")
def get_manager(manager_id: ManagerId, response: Response) -> ManagerResponse:
    """Get a manager's FPL team: team and manager name, points, rank and team value.

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
def get_transfers(manager_id: ManagerId, response: Response) -> List[TransferResponse]:
    """List a manager's transfers this season, newest first.

    Returns 404 if FPL has no such manager, and 503 if FPL can't be reached.
    """
    try:
        result = managers.get_transfers(manager_id)
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
