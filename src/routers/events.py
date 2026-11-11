from typing import List
from fastapi import APIRouter, HTTPException
from src.models.event import EventResponse, LiveElementResponse
from src.routers.live import Live
from src.routers.params import EventId
from src.services import events
from src.util.database import DataSession
from src.util.fpl_client import FplNotFoundError

events_router = APIRouter()

# Live points change by the minute during matches. Vercel's CDN serves a cached
# copy for up to s-maxage seconds, then one stale copy while it refreshes.
LIVE_CACHE = "s-maxage=60, stale-while-revalidate=60"


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
            List[LiveElementResponse],
            LIVE_CACHE,
            lambda: events.get_live(event_id),
        )
    except FplNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Event not found",
            headers={"Cache-Control": "no-store"},
        ) from exc
