from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.db.models import Event
from src.models.event import EventResponse


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
