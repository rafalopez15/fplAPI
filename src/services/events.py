from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.db.models import Event
from src.models.event import EventResponse, LiveElementResponse
from src.models.fixture import LiveFixtureResponse
from src.services.fpl_rows import readable
from src.util import fpl_client


def get_events(session: Session) -> List[EventResponse]:
    """Return every gameweek, in order. FPL calls gameweeks "events"."""
    rows = session.scalars(select(Event).order_by(Event.id))
    return [EventResponse.model_validate(row) for row in rows]


def get_event_by_id(session: Session, event_id: int) -> Optional[EventResponse]:
    """Return the gameweek with this id, or None. Ids match gameweek numbers."""
    row = session.get(Event, event_id)
    return EventResponse.model_validate(row) if row else None


def get_current_event(session: Session) -> Optional[EventResponse]:
    """Return the gameweek marked is_current, or None, e.g. before the season starts."""
    row = session.scalars(select(Event).where(Event.is_current)).first()
    return EventResponse.model_validate(row) if row else None


def get_live(event_id: int) -> List[LiveElementResponse]:
    """Return every player's points and minutes in a gameweek, in id order.

    Unlike the functions above, this calls FPL live, because the points change
    during matches. Empty for a gameweek that hasn't started. Raises
    FplNotFoundError for a gameweek FPL doesn't have and FplUnavailableError when
    FPL can't be reached.
    """
    items = fpl_client.fetch_event_live(event_id).get("elements", [])
    return [
        LiveElementResponse.model_validate({"id": item["id"], **item.get("stats", {})})
        for item in items
    ]


def get_fixtures(session: Session, event_id: int) -> List[LiveFixtureResponse]:
    """Return a gameweek's matches by kickoff, live from FPL.

    FPL answers [] for unknown and fully postponed gameweeks alike, so [] is
    FplNotFoundError unless the gameweek is stored.
    """
    rows = fpl_client.fetch_event_fixtures(event_id)
    if not isinstance(rows, list):
        raise fpl_client.FplUnavailableError("FPL sent fixtures that aren't a list")
    if not rows:
        if session.get(Event, event_id) is None:
            raise fpl_client.FplNotFoundError(f"No event {event_id}")
        return []
    fixtures = readable(rows, LiveFixtureResponse, "fixture", "id")
    return sorted(
        fixtures,
        key=lambda fixture: (
            fixture.kickoff_time is None,
            fixture.kickoff_time.timestamp() if fixture.kickoff_time else 0,
            fixture.id,
        ),
    )
