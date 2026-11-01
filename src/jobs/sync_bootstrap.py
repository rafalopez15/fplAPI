"""Sync FPL's bootstrap-static into Postgres. GitHub Actions runs it hourly.

    python -m src.jobs.sync_bootstrap

Upserts teams, element_types, elements and events in one transaction, so a failed
run leaves the previous data in place. Unchanged rows aren't rewritten, and rows
are never deleted: players FPL drops stay for their history. Every run is
recorded in sync_runs.
"""
import logging
import sys
from typing import Callable, Optional
import requests
from sqlalchemy import Engine, func, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from src.db.models import Base, Element, ElementType, Event, SyncRun, Team
from src.util import database
from src.util.fpl_service import fetch_bootstrap_static

logger = logging.getLogger(__name__)

# FPL's collection name and its table, in foreign-key order.
COLLECTIONS = (
    ("teams", Team),
    ("element_types", ElementType),
    ("elements", Element),
    ("events", Event),
)

# Failures this job records and survives. Anything else is a bug and should crash.
SYNC_ERRORS = (
    requests.exceptions.RequestException,
    SQLAlchemyError,
    KeyError,
    TypeError,
    AttributeError,
)

MAX_ERROR_LENGTH = 2000


def to_row(model: type[Base], item: dict) -> dict:
    """Map one FPL record onto a table row.

    Every column gets a value and FPL's extra fields are dropped. A column FPL
    doesn't send becomes None, so a missing required field fails the sync instead
    of leaving a stale value behind.
    """
    row = {
        column.name: item.get(column.name)
        for column in model.__table__.columns
        if column.name != "updated_at"
    }
    if model is Event:
        row["top_element_points"] = (item.get("top_element_info") or {}).get("points")
    return row


def upsert(session: Session, model: type[Base], rows: list[dict]) -> int:
    """Insert new rows and update changed ones. Returns how many were written.

    Rows identical to what's stored are skipped by Postgres itself, so they get no
    new row version and keep their updated_at: updated_at means "last changed".
    """
    if not rows:
        return 0
    statement = insert(model).values(rows)
    keys = [column.name for column in model.__table__.primary_key]
    columns = [name for name in rows[0] if name not in keys]
    changes = {name: statement.excluded[name] for name in columns}
    changes["updated_at"] = func.now()
    stored = tuple_(*(model.__table__.c[name] for name in columns))
    incoming = tuple_(*(statement.excluded[name] for name in columns))
    statement = statement.on_conflict_do_update(
        index_elements=keys, set_=changes, where=stored.is_distinct_from(incoming)
    )
    # RETURNING lists only the rows Postgres inserted or updated, not skipped ones.
    # (rowcount isn't reliable for multi-row inserts.)
    returned = session.execute(statement.returning(*model.__table__.primary_key))
    return len(returned.all())


def describe(error: Exception) -> str:
    """A short error message for sync_runs and the log.

    Database errors keep only the driver's message: the full SQLAlchemy message
    includes every parameter, which is hundreds of rows here.
    """
    return str(getattr(error, "orig", None) or error)[:MAX_ERROR_LENGTH]


def sync_bootstrap(
    engine: Optional[Engine] = None,
    fetch: Callable[[], dict] = fetch_bootstrap_static,
) -> bool:
    """Run one sync and return whether it succeeded.

    Raises SQLAlchemyError only if the run can't be recorded at all, e.g. when the
    database is unreachable.
    """
    engine = engine or database.engine
    with Session(engine) as session, session.begin():
        run = SyncRun(kind="bootstrap", status="running")
        session.add(run)
        session.flush()
        run_id = run.id

    try:
        data = fetch()
        with Session(engine) as session, session.begin():
            for collection, model in COLLECTIONS:
                rows = [to_row(model, item) for item in data[collection]]
                written = upsert(session, model, rows)
                logger.info("Upserted %s %s (%s new or changed)", len(rows), collection, written)
        status, error = "succeeded", None
    except SYNC_ERRORS as exc:
        status, error = "failed", describe(exc)
        logger.error("Bootstrap sync failed: %s", error)

    with Session(engine) as session, session.begin():
        session.execute(
            update(SyncRun)
            .where(SyncRun.id == run_id)
            .values(status=status, error=error, finished_at=func.now())
        )
    return status == "succeeded"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        succeeded = sync_bootstrap()
    except SQLAlchemyError as exc:
        logger.error("Could not record the sync run: %s", describe(exc))
        return 1
    return 0 if succeeded else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
