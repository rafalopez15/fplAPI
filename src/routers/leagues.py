from typing import Annotated, Optional
from fastapi import APIRouter, HTTPException, Query, Response
from src.models.league import LeagueActivityResponse, LeagueStandingsResponse
from src.routers.live import Live, LiveRoute
from src.routers.params import LeagueId, POSTGRES_INT_MAX
from src.services import league_activity, leagues
from src.util.database import DataSession
from src.util.fpl_client import FplNotFoundError

leagues_router = APIRouter()

# Standings move during a gameweek, but a few minutes old is fine for a league page.
LEAGUE_CACHE = "s-maxage=300, stale-while-revalidate=600"
# The gameweek pass updates activity hourly.
ACTIVITY_CACHE = "s-maxage=300"

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
        raise not_found("League not found") from exc


@leagues_router.get("/leagues/{league_id}/activity")
def get_league_activity(
    league_id: LeagueId,
    session: DataSession,
    response: Response,
    event: Annotated[
        Optional[int],
        Query(
            gt=0,
            le=POSTGRES_INT_MAX,
            description="The gameweek; by default the latest past its deadline",
        ),
    ] = None,
) -> LeagueActivityResponse:
    """Get what each team in a classic league did in a gameweek: real transfers, the
    hit, chip and captain, by team id. Never managers' real names.

    Read from what the hourly gameweek pass stored. The first request for a league
    checks it with FPL and starts tracking it, answering pending with no teams until
    the next pass. Returns 404 for an unknown league (head-to-head ones included) or
    gameweek, or one whose deadline hasn't passed; 422 for a league with more than
    50 teams; 429 when no more leagues can be tracked for now; 503 if FPL can't be
    reached to check a new league.
    """
    try:
        gameweek = league_activity.resolve_event(session, event)
    except league_activity.EventNotFoundError as exc:
        raise not_found("Event not found") from exc
    except league_activity.DeadlineNotPassedError as exc:
        raise not_found("Event deadline hasn't passed") from exc
    try:
        league_activity.track(session, league_id)
    except FplNotFoundError as exc:
        raise not_found("League not found") from exc
    except league_activity.LeagueTooBigError as exc:
        # A big league stays big, so the CDN can answer repeats for an hour.
        raise HTTPException(
            status_code=422,
            detail="League too big for activity",
            headers={"Cache-Control": "s-maxage=3600"},
        ) from exc
    except league_activity.TooManyLeaguesError as exc:
        raise HTTPException(
            status_code=429,
            detail="Too many leagues tracked, try again later",
            headers={
                "Retry-After": str(league_activity.RETRY_AFTER),
                "Cache-Control": "no-store",
            },
        ) from exc
    response.headers["Cache-Control"] = ACTIVITY_CACHE
    return league_activity.get_activity(session, league_id, gameweek)


def not_found(detail: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail=detail, headers={"Cache-Control": "no-store"}
    )
