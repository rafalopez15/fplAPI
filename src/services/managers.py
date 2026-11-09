"""FPL managers. Unlike the other services, these call FPL live: manager data is
per user and can't be synced ahead of time. Vercel's CDN caches the responses
(see the router), so repeat requests don't reach FPL.

Every function raises FplNotFoundError for an unknown manager and
FplUnavailableError when FPL can't be reached.
"""

import logging
from typing import List, Optional
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from src.models.manager import (
    League,
    HistoryResponse,
    ManagerResponse,
    PicksResponse,
    TransferResponse,
)
from src.services import transfer_points
from src.util import fpl_client

logger = logging.getLogger(__name__)


def get_manager(manager_id: int) -> ManagerResponse:
    manager = fpl_client.fetch_manager(manager_id)
    return ManagerResponse.model_validate(
        {**manager, "leagues": _classic_leagues(manager)}
    )


LEAGUE_KINDS = {"x": "invitational", "s": "system"}


def _classic_leagues(manager: dict) -> List[League]:
    """The team's classic leagues, invitational first, each group smallest first.

    Head-to-head leagues, and leagues missing an id or name, of a type we don't
    know, or with fields we can't read, are left out rather than failing the whole
    response.
    """
    found = []
    for raw in (manager.get("leagues") or {}).get("classic") or []:
        if not (
            raw.get("scoring") == "c"
            and raw.get("league_type") in LEAGUE_KINDS
            and raw.get("id") is not None
            and raw.get("name")
        ):
            continue
        try:
            found.append(
                League(
                    id=raw["id"],
                    name=raw["name"],
                    kind=LEAGUE_KINDS[raw["league_type"]],
                    size=raw.get("rank_count"),
                    rank=raw.get("entry_rank"),
                    last_rank=raw.get("entry_last_rank"),
                )
            )
        except ValidationError as exc:
            logger.warning("Skipping unreadable league %r: %s", raw.get("id"), exc)
    # Leagues FPL gives no size go last in their group.
    return sorted(
        found,
        key=lambda league: (
            league.kind != "invitational",
            league.size is None,
            league.size or 0,
            league.id,
        ),
    )


def get_transfers(manager_id: int, session: Session) -> List[TransferResponse]:
    """Return the manager's transfers this season, newest first, with net points.

    Calls FPL twice (transfers, then history for the Free Hit gameweeks) and reads
    the stored gameweek points. If the database can't be read, the transfers still
    come back, with null points.
    """
    transfers = fpl_client.fetch_manager_transfers(manager_id)
    if not transfers:
        return []
    chips = fpl_client.fetch_manager_history(manager_id).get("chips", [])
    free_hits = {chip.get("event") for chip in chips if chip.get("name") == "freehit"}
    players = {row[key] for row in transfers for key in ("element_in", "element_out")}
    try:
        data = transfer_points.load_points(session, players)
    except SQLAlchemyError as exc:
        logger.warning("Transfer points unavailable: %s", exc)
        data = None
    rows = transfer_points.with_net_points(transfers, free_hits, data)
    results = [TransferResponse.model_validate(row) for row in rows]
    return sorted(results, key=lambda transfer: transfer.time, reverse=True)


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
    return PicksResponse.model_validate(
        fpl_client.fetch_manager_picks(manager_id, event)
    )
