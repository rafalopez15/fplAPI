import logging
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Optional
from fastapi import Depends
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from src.db.models import SyncRun
from src.util.config import (
    DATABASE_CONNECT_TIMEOUT,
    DATABASE_MAX_OVERFLOW,
    DATABASE_POOL_SIZE,
    DATABASE_URL,
)

logger = logging.getLogger(__name__)

# Creating the engine doesn't connect; connections open on first use.
# pool_pre_ping replaces connections the pooler has closed while idle.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=DATABASE_POOL_SIZE,
    max_overflow=DATABASE_MAX_OVERFLOW,
    connect_args={"connect_timeout": DATABASE_CONNECT_TIMEOUT},
)


class FplDataUnavailableError(Exception):
    """Raised when no bootstrap sync has succeeded yet, so there's no FPL data to serve."""


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, closed afterwards."""
    with Session(engine) as session:
        yield session


def last_successful_sync(session: Session) -> Optional[datetime]:
    """When the last successful bootstrap sync finished, or None if none has."""
    return session.scalar(
        select(func.max(SyncRun.finished_at)).where(
            SyncRun.kind == "bootstrap", SyncRun.status == "succeeded"
        )
    )


def get_data_session(session: Annotated[Session, Depends(get_session)]) -> Session:
    """FastAPI dependency for endpoints that serve FPL data.

    Raises FplDataUnavailableError (503) until the first bootstrap sync succeeds,
    so an empty database isn't mistaken for "no teams" or "no players".
    """
    if last_successful_sync(session) is None:
        raise FplDataUnavailableError("No bootstrap sync has succeeded yet")
    return session


DataSession = Annotated[Session, Depends(get_data_session)]


def is_database_reachable() -> bool:
    """Run SELECT 1 and report whether it worked. Never raises."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as exc:
        logger.warning("Database check failed: %s", exc)
        return False


def get_last_sync() -> Optional[datetime]:
    """last_successful_sync() with its own session, for /healthcheck. Never raises."""
    try:
        with Session(engine) as session:
            return last_successful_sync(session)
    except SQLAlchemyError as exc:
        logger.warning("Couldn't read the last sync time: %s", exc)
        return None
