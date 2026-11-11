"""FPL leagues, called live like the managers. Raises FplNotFoundError for an
unknown league and FplUnavailableError when FPL can't be reached."""

import logging
from typing import List, Type, TypeVar
from pydantic import BaseModel, ValidationError
from src.models.league import LeagueStandingsResponse, NewEntry, Standing
from src.util import fpl_client

logger = logging.getLogger(__name__)

Row = TypeVar("Row", bound=BaseModel)


def get_standings(league_id: int, page: int = 1) -> LeagueStandingsResponse:
    data = fpl_client.fetch_league_standings(league_id, page)
    league = data.get("league") or {}
    if not league.get("name"):
        raise fpl_client.FplUnavailableError("FPL sent standings without a league")
    standings = data.get("standings") or {}
    new_entries = data.get("new_entries") or {}
    return LeagueStandingsResponse(
        id=league.get("id") or league_id,
        name=league["name"],
        last_updated=data.get("last_updated_data"),
        page=standings.get("page", page),
        has_next=standings.get("has_next", False),
        standings=_readable(standings.get("results") or [], Standing),
        new_entries=_readable(new_entries.get("results") or [], NewEntry),
        new_entries_has_next=new_entries.get("has_next", False),
    )


def _readable(rows: list, model: Type[Row]) -> List[Row]:
    """Rows we can't read are left out rather than failing the page."""
    found = []
    for row in rows:
        try:
            found.append(model.model_validate(row))
        except ValidationError as exc:
            logger.warning("Skipping unreadable standing %r: %s", row.get("entry"), exc)
    return found
