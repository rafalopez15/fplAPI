"""Responses for the manager endpoints, built from FPL's entry/{id}/ endpoints.

Field names are FPL's. Only identity fields are required, so a field FPL drops
comes back as null instead of failing the request.
"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class ManagerResponse(BaseModel):
    """A manager's FPL team, from entry/{id}/. FPL's leagues, kit and badge are left out."""
    id: int
    name: str  # the team's name
    player_first_name: str  # the manager's name
    player_last_name: str
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
    """One transfer, from entry/{id}/transfers/. Costs are in tenths of a million."""
    element_in: int
    element_out: int
    event: int
    time: datetime
    element_in_cost: Optional[int] = None
    element_out_cost: Optional[int] = None


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
