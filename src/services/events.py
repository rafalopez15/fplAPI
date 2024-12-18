import logging
from src.models.event import EventResponse
from src.util.fpl_service import FplService

logger = logging.getLogger(__name__)


def get_events():
    events = FplService().fpl_data.get("events")
    return events


def get_event_by_id(id: int):
    events = get_events()
    for event in events:
        if event.get("id") == id:
            return event

    return None


async def get_current_event():
    try:
        await FplService().get_fpl_api_data()
    except Exception as e:
        logger.exception("Failed to fetch current FPL data", e, exc_info=True)
    events = get_events()
    for event in events:
        if event.get("is_current"):
            return EventResponse(**event)

    return None
