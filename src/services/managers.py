"""FPL managers. Unlike the other services, these call FPL live: manager data is
per user and can't be synced ahead of time. Vercel's CDN caches the responses
(see the router), so repeat requests don't reach FPL.

Every function raises FplNotFoundError for an unknown manager and
FplUnavailableError when FPL can't be reached.
"""
from typing import List, Optional
from src.models.manager import (
    HistoryResponse,
    ManagerResponse,
    PicksResponse,
    TransferResponse,
)
from src.util import fpl_client


def get_manager(manager_id: int) -> ManagerResponse:
    return ManagerResponse.model_validate(fpl_client.fetch_manager(manager_id))


def get_transfers(manager_id: int) -> List[TransferResponse]:
    """Return the manager's transfers this season, newest first, as FPL orders them."""
    return [
        TransferResponse.model_validate(item)
        for item in fpl_client.fetch_manager_transfers(manager_id)
    ]


def get_history(manager_id: int) -> HistoryResponse:
    return HistoryResponse.model_validate(fpl_client.fetch_manager_history(manager_id))


def get_picks(manager_id: int, event: Optional[int] = None) -> Optional[PicksResponse]:
    """Return the manager's squad for a gameweek, by default their current one.

    The default is the manager's current_event (the latest gameweek whose deadline
    has passed), which takes an extra call to FPL. Returns None if there's no
    current gameweek yet, e.g. before the season's first deadline.
    """
    if event is None:
        event = fpl_client.fetch_manager(manager_id).get("current_event")
        if event is None:
            return None
    return PicksResponse.model_validate(fpl_client.fetch_manager_picks(manager_id, event))
