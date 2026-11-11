"""The last good response of each route that calls FPL live, so it can be served
while FPL is down, e.g. for the hour or more after a deadline while the game updates.

Snapshots are stored as the API returned them, after the response models have left
out what never leaves the API. save and load never raise for a database error: a
failed save just means no snapshot, and a failed load means a 503, as without one.
The hourly sync purges old ones.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from src.db.models import FplSnapshot

logger = logging.getLogger(__name__)

# A snapshot is refreshed whenever its route reaches FPL, so one this old belongs
# to a team or league nobody has looked at since.
MAX_AGE = timedelta(days=30)


def save(session: Session, key: str, result: Any, kind: Any) -> None:
    """Store result, a response of type kind, as the latest snapshot for key."""
    body = TypeAdapter(kind).dump_python(result, mode="json")
    stmt = insert(FplSnapshot).values(key=key, body=body, fetched_at=func.now())
    stmt = stmt.on_conflict_do_update(
        index_elements=[FplSnapshot.key],
        set_={"body": stmt.excluded.body, "fetched_at": stmt.excluded.fetched_at},
    )
    try:
        session.execute(stmt)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.warning("Couldn't save snapshot %s: %s", key, exc)


def load(session: Session, key: str, kind: Any) -> Optional[Tuple[Any, datetime]]:
    """Return key's snapshot as a kind, and when it was fetched, or None.

    None also when the database can't be read, or when the snapshot no longer fits
    kind (the model changed since it was saved), since it can't be served as is.
    """
    try:
        row = session.get(FplSnapshot, key)
    except SQLAlchemyError as exc:
        logger.warning("Couldn't load snapshot %s: %s", key, exc)
        return None
    if row is None:
        return None
    try:
        return TypeAdapter(kind).validate_python(row.body), row.fetched_at
    except ValidationError as exc:
        logger.warning("Snapshot %s no longer fits its model: %s", key, exc)
        return None


def purge(session: Session) -> int:
    """Delete snapshots older than MAX_AGE. Returns how many."""
    result = session.execute(
        delete(FplSnapshot).where(FplSnapshot.fetched_at < func.now() - MAX_AGE)
    )
    return result.rowcount
