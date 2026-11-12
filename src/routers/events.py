from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.models.event import EventResponse, LiveElementResponse
from src.models.fixture import LiveFixtureResponse
from src.routers.live import Live, LiveRoute
from src.routers.params import EventId
from src.services import events
from src.util.database import DataSession, get_session
from src.util.fpl_client import FplNotFoundError

events_router = APIRouter()

# Live points change by the minute during matches. Vercel's CDN serves a cached
# copy for up to s-maxage seconds, then one stale copy while it refreshes.
LIVE_CACHE = "s-maxage=60, stale-while-revalidate=60"

# A gameweek that hasn't started is [], not worth saving.
LIVE = LiveRoute(List[LiveElementResponse], LIVE_CACHE, keep=bool)
# [] for a gameweek with every match postponed, or none readable.
FIXTURES = LiveRoute(List[LiveFixtureResponse], LIVE_CACHE, keep=bool)


@events_router.get("/events")
def get_events(session: DataSession) -> List[EventResponse]:
    """List every gameweek."""
    return events.get_events(session)


@events_router.get("/events/{event_id}")
def get_event_by_id(session: DataSession, event_id: EventId) -> EventResponse:
    """Get one gameweek by its number, e.g. 1 for Gameweek 1. Returns 404 if it
    doesn't exist."""
    result = events.get_event_by_id(session, event_id)
    if not result:
        raise HTTPException(status_code=404, detail="Event not found")

    return result


@events_router.get("/events/current-event/")
def get_current_event(session: DataSession) -> EventResponse:
    """Get the current gameweek. Returns 404 when no gameweek is current."""
    result = events.get_current_event(session)
    if not result:
        raise HTTPException(status_code=404, detail="Current event not found")

    return result


@events_router.get("/events/{event_id}/live")
def get_live(event_id: EventId, live: Live) -> List[LiveElementResponse]:
    """List every player's points and minutes in a gameweek, updated during matches.

    Calls FPL live, so it works even when the hourly sync is behind. Returns [] for
    a gameweek that hasn't started, and 404 if FPL has no such gameweek. If FPL
    can't be reached, returns the last copy saved, with X-Data-Stale-As-Of, or 503
    without one.
    """
    try:
        return live.call(
            f"events/{event_id}/live",
            LIVE,
            lambda: events.get_live(event_id),
        )
    except FplNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Event not found",
            headers={"Cache-Control": "no-store"},
        ) from exc


@events_router.get("/events/{event_id}/fixtures")
def get_fixtures(
    event_id: EventId,
    live: Live,
    session: Annotated[Session, Depends(get_session)],
) -> List[LiveFixtureResponse]:
    """List a gameweek's matches by kickoff, with scores and minutes during play.

    Calls FPL live. finished_provisional is true at full time, before FPL confirms
    the bonus points and sets finished. Returns [] for a gameweek with every match
    postponed, and 404 for a gameweek that doesn't exist. If FPL can't be reached,
    returns the last copy saved, with X-Data-Stale-As-Of, or 503 without one. Uses
    a plain session, not DataSession, like Live.
    """
    try:
        return live.call(
            f"events/{event_id}/fixtures",
            FIXTURES,
            lambda: events.get_fixtures(session, event_id),
        )
    except FplNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Event not found",
            headers={"Cache-Control": "no-store"},
        ) from exc
