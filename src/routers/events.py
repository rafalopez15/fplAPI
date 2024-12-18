from fastapi import APIRouter, HTTPException
from src.models.event import EventResponse
from src.services import events

events_router = APIRouter()


@events_router.get("/events")
async def get_events():
    result = events.get_events()
    if not result:
        raise HTTPException(status_code=400, detail="Not able to retrieve events")

    return result


@events_router.get("/events/{event_id}")
async def get_event_by_id(event_id: int):
    result = events.get_event_by_id(event_id)
    if not result:
        raise HTTPException(status_code=404, detail="Event not found")

    return result


@events_router.get("/events/current-event/")
async def get_current_event() -> EventResponse:
    result = await events.get_current_event()
    if not result:
        raise HTTPException(status_code=404, detail="Current event not found")

    return result
