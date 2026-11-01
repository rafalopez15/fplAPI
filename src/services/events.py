from src.models.event import EventResponse
from src.util.fpl_service import FplService


def get_events():
    events = FplService().get_data("events")
    return events


def get_event_by_id(event_id: int):
    events = get_events()
    for event in events:
        if event.get("id") == event_id:
            return event

    return None


async def get_current_event():
    # Refresh so the current gameweek is up to date; on failure the cached data is used.
    await FplService().get_fpl_api_data()
    events = get_events()
    for event in events:
        if event.get("is_current"):
            return EventResponse(**event)

    return None
