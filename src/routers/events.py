from fastapi import APIRouter, HTTPException
from src.models.event import EventResponse
from src.services import events

events_router = APIRouter()


@events_router.get("/events")
async def get_events():
    """List every gameweek with all the fields FPL provides."""
    return events.get_events()


@events_router.get("/events/{event_id}")
async def get_event_by_id(event_id: int):
    """Get one gameweek by its number, e.g. 1 for Gameweek 1. Returns 404 if it doesn't exist."""
    result = events.get_event_by_id(event_id)
    if not result:
        raise HTTPException(status_code=404, detail="Event not found")

    return result


@events_router.get("/events/current-event/")
async def get_current_event() -> EventResponse:
    """Get the current gameweek.

    This refreshes the data from FPL first, so it's slower than the other
    endpoints. Returns 404 when no gameweek is current.
    """
    result = await events.get_current_event()
    if not result:
        raise HTTPException(status_code=404, detail="Current event not found")

    return result
