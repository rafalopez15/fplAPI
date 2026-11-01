from src.models.event import EventResponse
from src.util.fpl_service import FplService


def get_events():
    """Return every gameweek as the raw dicts FPL sends. FPL calls gameweeks "events"."""
    events = FplService().get_data("events")
    return events


def get_event_by_id(event_id: int):
    """Return the gameweek with this id, or None. Ids match gameweek numbers."""
    events = get_events()
    for event in events:
        if event.get("id") == event_id:
            return event

    return None


async def get_current_event():
    """Refresh the data from FPL, then return the gameweek marked is_current.

    If the refresh fails, this answers from the cached data. Returns None when no
    gameweek is current, for example before the season starts.
    """
    await FplService().get_fpl_api_data()
    events = get_events()
    for event in events:
        if event.get("is_current"):
            return EventResponse(**event)

    return None
