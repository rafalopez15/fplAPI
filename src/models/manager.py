"""Responses for the manager endpoints, built from FPL's entry/{id}/ endpoints.

Field names are FPL's. Only identity fields are required, so a field FPL drops
comes back as null instead of failing the request.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class ManagerResponse(BaseModel):
    """A manager's FPL team, from entry/{id}/. FPL's leagues, kit and badge are left
    out.

    So is the manager's real name (player_first_name, player_last_name): it never
    leaves the API. Next to anonymous comments it makes harassment easy (FPL-45).
    """

    id: int
    name: str  # the team's name, the only name the app shows
    current_event: Optional[int] = None
    started_event: Optional[int] = None
    favourite_team: Optional[int] = None
    player_region_name: Optional[str] = None
    summary_overall_points: Optional[int] = None
    summary_overall_rank: Optional[int] = None
    summary_event_points: Optional[int] = None
    summary_event_rank: Optional[int] = None
    # Money is in tenths of a million, like now_cost: 1022 is £102.2m.
    last_deadline_bank: Optional[int] = None
    last_deadline_value: Optional[int] = None
    last_deadline_total_transfers: Optional[int] = None


class TransferResponse(BaseModel):
    """One transfer, from entry/{id}/transfers/. Costs are in tenths of a million.

    is_churn marks a swap the manager undid in the same gameweek, e.g. while planning
    a Wildcard; the real transfers are the rest. Points are for the gameweeks the
    player was owned, and null for churn, before the first gameweek is finished, or
    when the stored points can't be read (services/transfer_points.py).
    """

    element_in: int
    element_out: int
    event: int
    time: datetime
    element_in_cost: Optional[int] = None
    element_out_cost: Optional[int] = None
    is_churn: bool = False
    points_in: Optional[int] = None
    points_out: Optional[int] = None
    net_points: Optional[int] = None


class GameweekHistory(BaseModel):
    """A manager's result in one gameweek. bank and value are in tenths of a million."""

    event: int
    points: Optional[int] = None
    total_points: Optional[int] = None
    rank: Optional[int] = None
    overall_rank: Optional[int] = None
    bank: Optional[int] = None
    value: Optional[int] = None
    event_transfers: Optional[int] = None
    event_transfers_cost: Optional[int] = None
    points_on_bench: Optional[int] = None


class ChipUsed(BaseModel):
    """A chip the manager played, e.g. "bboost" or "wildcard"."""

    name: str
    event: int
    time: Optional[datetime] = None


class PastSeason(BaseModel):
    season_name: str  # e.g. "2024/25"
    total_points: Optional[int] = None
    rank: Optional[int] = None


class HistoryResponse(BaseModel):
    """A manager's history, from entry/{id}/history/, with FPL's three lists."""

    current: List[GameweekHistory]
    chips: List[ChipUsed]
    past: List[PastSeason]


class Pick(BaseModel):
    """One player in a squad. position 1-11 is the starting XI, 12-15 the bench in
    order."""

    element: int
    position: int
    # 0 on the bench, 1 playing, 2 captain, 3 triple captain.
    multiplier: Optional[int] = None
    is_captain: Optional[bool] = None
    is_vice_captain: Optional[bool] = None
    element_type: Optional[int] = None


class AutomaticSub(BaseModel):
    """A bench player FPL brought on for a starter who didn't play."""

    element_in: int
    element_out: int
    event: int


class PicksResponse(BaseModel):
    """A manager's squad for one gameweek, from entry/{id}/event/{gw}/picks/.

    entry_history is the manager's result that gameweek; its event field says which
    gameweek this is.
    """

    active_chip: Optional[str] = None  # "wildcard", "freehit", "bboost", "3xc" or null
    picks: List[Pick]
    automatic_subs: List[AutomaticSub]
    entry_history: GameweekHistory
