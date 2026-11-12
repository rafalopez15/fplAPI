"""FPL leagues, called live like the managers. Raises FplNotFoundError for an
unknown league and FplUnavailableError when FPL can't be reached."""

from src.models.league import LeagueStandingsResponse, NewEntry, Standing
from src.services.fpl_rows import readable
from src.util import fpl_client


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
        standings=readable(
            standings.get("results") or [], Standing, "standing", "entry"
        ),
        new_entries=readable(
            new_entries.get("results") or [], NewEntry, "new entry", "entry"
        ),
        new_entries_has_next=new_entries.get("has_next", False),
    )
