"""Sync FPL's bootstrap-static and fixtures into Postgres. GitHub Actions runs it
hourly.

    python -m src.jobs.sync_bootstrap

Upserts teams, element_types, elements, events and fixtures in one transaction, so
a failed run leaves the previous data in place. Unchanged rows aren't rewritten, and
rows are never deleted: players FPL drops stay for their history. Every run is
recorded in sync_runs.

Then stores each newly finished gameweek's points per player (element_event_points),
one gameweek per transaction, so a failure there doesn't undo the bootstrap data.
Last, it fetches the names of teams on accounts that teams_tracked doesn't have.
"""

import logging
import sys
from typing import Callable, Optional
import requests
from sqlalchemy import Engine, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from src.db.models import (
    Base,
    Element,
    ElementEventPoints,
    ElementType,
    Event,
    Fixture,
    SyncRun,
    Team,
    TrackedTeam,
    UserTeam,
)
from src.services.user_teams import remember_team
from src.util import database
from src.util.fpl_client import (
    FplNotFoundError,
    FplUnavailableError,
    fetch_bootstrap_static,
    fetch_event_live,
    fetch_fixtures,
    fetch_manager,
)

logger = logging.getLogger(__name__)

# FPL's collection name and its table, in foreign-key order. "fixtures" comes
# from FPL's /fixtures/ endpoint; the rest from bootstrap-static.
COLLECTIONS = (
    ("teams", Team),
    ("element_types", ElementType),
    ("elements", Element),
    ("events", Event),
    ("fixtures", Fixture),
)

# Failures this job records and survives. Anything else is a bug and should crash.
SYNC_ERRORS = (
    requests.exceptions.RequestException,
    FplNotFoundError,
    FplUnavailableError,
    SQLAlchemyError,
    KeyError,
    TypeError,
    AttributeError,
)

MAX_ERROR_LENGTH = 2000
NAME_BATCH = 100  # team names fetched per run, at most


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


def start_run(engine: Engine, kind: str, event_id: Optional[int] = None) -> int:
    """Record a sync run as running and return its id."""
    with Session(engine) as session, session.begin():
        run = SyncRun(kind=kind, event_id=event_id, status="running")
        session.add(run)
        session.flush()
        return run.id


def finish_run(engine: Engine, run_id: int, status: str, error: Optional[str]) -> None:
    with Session(engine) as session, session.begin():
        session.execute(
            update(SyncRun)
            .where(SyncRun.id == run_id)
            .values(status=status, error=error, finished_at=func.now())
        )


def sync_bootstrap(
    engine: Optional[Engine] = None,
    fetch: Callable[[], dict] = fetch_bootstrap_static,
    fetch_fixtures_list: Callable[[], list] = fetch_fixtures,
) -> bool:
    """Run one sync and return whether it succeeded.

    Raises SQLAlchemyError only if the run can't be recorded at all, e.g. when the
    database is unreachable.
    """
    engine = engine or database.engine
    run_id = start_run(engine, "bootstrap")

    try:
        # Both fetches happen before any write, so a failed fetch writes nothing.
        data = {**fetch(), "fixtures": fetch_fixtures_list()}
        with Session(engine) as session, session.begin():
            for collection, model in COLLECTIONS:
                rows = [to_row(model, item) for item in data[collection]]
                written = upsert(session, model, rows)
                logger.info(
                    "Upserted %s %s (%s new or changed)", len(rows), collection, written
                )
        status, error = "succeeded", None
    except SYNC_ERRORS as exc:
        status, error = "failed", describe(exc)
        logger.error("Bootstrap sync failed: %s", error)

    finish_run(engine, run_id, status, error)
    return status == "succeeded"


def gameweeks_to_store(engine: Engine) -> list[int]:
    """Finished gameweeks (bonus confirmed) whose points aren't stored yet, in order."""
    stored = select(ElementEventPoints.event).distinct()
    with Session(engine) as session:
        return list(
            session.scalars(
                select(Event.id)
                .where(Event.data_checked, Event.id.not_in(stored))
                .order_by(Event.id)
            )
        )


def sync_event_points(
    engine: Optional[Engine] = None,
    fetch_live: Callable[[int], dict] = fetch_event_live,
) -> bool:
    """Store every player's points for each newly finished gameweek.

    A gameweek's points are final once FPL confirms its bonus (data_checked), so each
    is fetched once. Every gameweek is its own run and transaction; the first
    failure stops the job, and the next run retries from that gameweek. Returns
    whether every gameweek succeeded.
    """
    engine = engine or database.engine
    for event in gameweeks_to_store(engine):
        run_id = start_run(engine, "event_points", event)
        try:
            rows = [
                {
                    "element": item["id"],
                    "event": event,
                    "total_points": item["stats"].get("total_points"),
                    "minutes": item["stats"].get("minutes"),
                }
                for item in fetch_live(event)["elements"]
            ]
            with Session(engine) as session, session.begin():
                written = upsert(session, ElementEventPoints, rows)
            logger.info(
                "Stored gameweek %s points: %s players (%s new or changed)",
                event,
                len(rows),
                written,
            )
            finish_run(engine, run_id, "succeeded", None)
        except SYNC_ERRORS as exc:
            error = describe(exc)
            logger.error("Gameweek %s points sync failed: %s", event, error)
            finish_run(engine, run_id, "failed", error)
            return False
    return True


def sync_team_names(
    engine: Optional[Engine] = None,
    fetch: Callable[[int], dict] = fetch_manager,
) -> bool:
    """Fetch the names of teams on accounts that teams_tracked doesn't have yet.

    A team added through the API gets its name then (FPL-101); this fills in the
    rest, such as teams added before that, NAME_BATCH per run. A team FPL doesn't
    have is stored with a null name, so it isn't asked for again. The first other
    failure stops it until the next run. Returns whether it finished without one.
    """
    engine = engine or database.engine
    with Session(engine) as session:
        missing = list(
            session.scalars(
                select(UserTeam.manager_id)
                .distinct()
                .where(UserTeam.manager_id.not_in(select(TrackedTeam.manager_id)))
                .order_by(UserTeam.manager_id)
                .limit(NAME_BATCH)
            )
        )
    for manager_id in missing:
        try:
            name = fetch(manager_id).get("name")
        except FplNotFoundError:
            name = None
        except SYNC_ERRORS as exc:
            logger.error(
                "Team name sync stopped at team %s: %s", manager_id, describe(exc)
            )
            return False
        with Session(engine) as session, session.begin():
            remember_team(session, manager_id, name)
    if missing:
        logger.info("Stored the names of %s team(s)", len(missing))
    return True


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        # The points sync runs even if the bootstrap one failed: it only needs
        # events.data_checked, which an older bootstrap sync has already stored.
        succeeded = sync_bootstrap()
        succeeded = sync_event_points() and succeeded
        succeeded = sync_team_names() and succeeded
    except SQLAlchemyError as exc:
        logger.error("Could not record the sync run: %s", describe(exc))
        return 1
    return 0 if succeeded else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
