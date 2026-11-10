"""Responses for the league endpoint, built from FPL's leagues-classic/{id}/standings/.

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
