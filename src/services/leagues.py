"""FPL leagues, called live like the managers. Raises FplNotFoundError for an
unknown league and FplUnavailableError when FPL can't be reached."""

from src.models.league import LeagueStandingsResponse
from src.util import fpl_client


def get_standings(league_id: int, page: int = 1) -> LeagueStandingsResponse:
    data = fpl_client.fetch_league_standings(league_id, page)
    league = data.get("league") or {}
    standings = data.get("standings") or {}
    return LeagueStandingsResponse.model_validate(
        {
            "id": league.get("id"),
            "name": league.get("name"),
            "last_updated": data.get("last_updated_data"),
            "page": standings.get("page", page),
            "has_next": standings.get("has_next", False),
            "standings": standings.get("results") or [],
        }
    )
