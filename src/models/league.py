"""Responses for the league endpoints: standings, built from FPL's
leagues-classic/{id}/standings/, and activity, from what the gameweek pass stored.

Field names are FPL's. Only identity fields are required, so a field FPL drops
comes back as null instead of failing the request.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class Standing(BaseModel):
    """One team's row. Never the manager's real name (FPL's player_name)."""

    entry: int  # the team's manager id, for /api/managers/{id}
    entry_name: str
    rank: Optional[int] = None
    last_rank: Optional[int] = None
    total: Optional[int] = None
    event_total: Optional[int] = None


class NewEntry(BaseModel):
    """A team that joined since standings were last updated. No rank yet, and
    never the manager's real name."""

    entry: int
    entry_name: str


class LeagueStandingsResponse(BaseModel):
    """A page of a classic league's standings, 50 teams a page, and the first 50
    teams that joined since the last update."""

    id: int
    name: str
    last_updated: Optional[datetime] = None
    page: int
    has_next: bool = False
    standings: List[Standing] = []
    new_entries: List[NewEntry] = []
    new_entries_has_next: bool = False


class ActivityTransfer(BaseModel):
    element_in: int
    element_out: int


class TeamActivity(BaseModel):
    """What one team did in a gameweek. Never the manager's real name."""

    entry: int
    entry_name: Optional[str] = None
    event: int
    # Real changes only: Wildcard and Free Hit churn is left out.
    transfers: List[ActivityTransfer] = []
    transfers_cost: int = 0  # the hit, in points
    chip: Optional[str] = None
    captain: Optional[int] = None
    vice_captain: Optional[int] = None
    captain_changed: Optional[bool] = None  # null for a team's first stored gameweek
    # Before the hit, as FPL shows it. Null until the gameweek's points are final.
    points: Optional[int] = None


class LeagueActivityResponse(BaseModel):
    """What each team in a classic league did in a gameweek, by team id.

    pending is true while the gameweek pass hasn't reached every team for this
    gameweek, e.g. for a league requested for the first time; teams it has reached
    are listed already.
    """

    league_id: int
    event: int
    pending: bool
    teams: List[TeamActivity] = []
