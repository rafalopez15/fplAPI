from typing import Annotated
from fastapi import APIRouter, HTTPException, Query, Response
from src.models.league import LeagueStandingsResponse
from src.routers.params import LeagueId, POSTGRES_INT_MAX
from src.services import leagues
from src.util.fpl_client import FplNotFoundError

leagues_router = APIRouter()

# Standings move during a gameweek, but a few minutes old is fine for a league page.
LEAGUE_CACHE = "s-maxage=300, stale-while-revalidate=600"


@leagues_router.get("/leagues/{league_id}")
def get_league(
    league_id: LeagueId,
    response: Response,
    page: Annotated[
        int, Query(gt=0, le=POSTGRES_INT_MAX, description="The page, 50 teams each")
    ] = 1,
) -> LeagueStandingsResponse:
    """Get a page of a classic league's standings, by rank. Never managers' real
    names.

    A page past the end has no standings. Returns 404 if FPL has no such classic
    league (head-to-head ones included), and 503 if FPL can't be reached.
    """
    try:
        result = leagues.get_standings(league_id, page)
    except FplNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="League not found",
            headers={"Cache-Control": "no-store"},
        ) from exc
    response.headers["Cache-Control"] = LEAGUE_CACHE
    return result
