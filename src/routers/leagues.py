from typing import Annotated
from fastapi import APIRouter, HTTPException, Query
from src.models.league import LeagueStandingsResponse
from src.routers.live import Live, LiveRoute
from src.routers.params import LeagueId, POSTGRES_INT_MAX
from src.services import leagues
from src.util.fpl_client import FplNotFoundError

leagues_router = APIRouter()

# Standings move during a gameweek, but a few minutes old is fine for a league page.
LEAGUE_CACHE = "s-maxage=300, stale-while-revalidate=600"

# Only the first page is saved: the apps show the top 50 only. A new league's first
# page has no standings but lists its teams in new_entries, so it's kept.
LEAGUE = LiveRoute(
    LeagueStandingsResponse,
    LEAGUE_CACHE,
    keep=lambda page: page.page == 1 and bool(page.standings or page.new_entries),
)


@leagues_router.get("/leagues/{league_id}")
def get_league(
    league_id: LeagueId,
    live: Live,
    page: Annotated[
        int, Query(gt=0, le=POSTGRES_INT_MAX, description="The page, 50 teams each")
    ] = 1,
) -> LeagueStandingsResponse:
    """Get a page of a classic league's standings, by rank. Never managers' real
    names.

    A page past the end has no standings. Returns 404 if FPL has no such classic
    league (head-to-head ones included). If FPL can't be reached, returns the first
    page's last copy saved, with X-Data-Stale-As-Of, or 503 without one or for any
    other page.
    """
    try:
        return live.call(
            f"leagues/{league_id}/{page}",
            LEAGUE,
            lambda: leagues.get_standings(league_id, page),
        )
    except FplNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="League not found",
            headers={"Cache-Control": "no-store"},
        ) from exc
