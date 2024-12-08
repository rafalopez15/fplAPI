from src.util.fpl_service import FplService


def get_events():
    events = FplService().fpl_data.get("events")
    return events


def get_event_by_id(id: int):
    events = get_events()
    for event in events:
        if event.get("id") == id:
            return event

    return None
