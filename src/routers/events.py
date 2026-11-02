from typing import List
from fastapi import APIRouter, HTTPException
from src.models.event import EventResponse
from src.services import events
from src.util.database import DataSession

events_router = APIRouter()


@events_router.get("/events")
def get_events(session: DataSession) -> List[EventResponse]:
    """List every gameweek."""
    return events.get_events(session)


@events_router.get("/events/{event_id}")
def get_event_by_id(session: DataSession, event_id: int) -> EventResponse:
    """Get one gameweek by its number, e.g. 1 for Gameweek 1. Returns 404 if it doesn't exist."""
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
