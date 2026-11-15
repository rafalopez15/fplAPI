"""The gameweek pass: store what each team in a tracked league did each gameweek.
GitHub Actions runs it hourly, after the bootstrap sync, as its own job.

    python -m src.jobs.gameweek_pass

It stops tracking leagues nobody has asked about for 14 days, refreshes each tracked
league's teams, then for every team behind the latest gameweek whose deadline has
passed fetches its transfers once and its picks for each gameweek it's missing,
backfilling a new team's whole season. Calls are paced at about 5 a second, and the
pass stops at a time limit; teams_tracked.last_event lets the next run carry on.
Each team commits on its own, so a migration waits seconds, not the whole pass. FPL
being down or updating stops the pass until the next run. Every run is recorded in
sync_runs (kind "team_gameweeks").
"""

import logging
import sys
import time
from typing import Optional
from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from src.db.models import Element, TrackedLeague
from src.jobs.sync_bootstrap import SYNC_ERRORS, describe, finish_run, start_run
from src.services import league_activity, leagues, team_gameweeks
from src.services.transfer_points import real_transfers
from src.util import database
from src.util.config import GAMEWEEK_PASS_MINUTES
from src.util.fpl_client import (
    FplNotFoundError,
    fetch_manager_picks,
    fetch_manager_transfers,
)
from src.util.fpl_metrics import calls_from

logger = logging.getLogger(__name__)

PACE = 0.2  # seconds between FPL calls, about 5 a second


class TimeUp(Exception):
    """The pass reached its time limit."""


class Pacer:
    """Spaces FPL calls PACE apart, and raises TimeUp once the time limit passes."""

    def __init__(self, minutes: float):
        self.deadline = time.monotonic() + minutes * 60
        self.last: Optional[float] = None

    def wait(self) -> None:
        now = time.monotonic()
        if now >= self.deadline:
            raise TimeUp
        if self.last is not None and now - self.last < PACE:
            time.sleep(PACE - (now - self.last))
        self.last = time.monotonic()


def refresh_league(engine: Engine, pacer: Pacer, league_id: int) -> None:
    """Store the league's current teams. A league FPL no longer has is dropped."""
    pacer.wait()
    try:
        standings = leagues.get_standings(league_id)
    except FplNotFoundError:
        logger.info("League %s no longer exists; stopped tracking it", league_id)
        with Session(engine) as session, session.begin():
            session.execute(
                delete(TrackedLeague).where(TrackedLeague.league_id == league_id)
            )
        return
    with Session(engine) as session, session.begin():
        league_activity.save_teams(session, league_id, standings)


def pass_team(engine: Engine, pacer: Pacer, team: tuple, latest: int, types: dict):
    """Store the gameweeks the team is missing, up to latest, and save how far it
    got even if the pass stops part-way.

    team is (manager_id, last_event). A 404 for picks means the team hadn't started
    that gameweek, except for the latest, which FPL may not have published yet:
    that's left for the next run.
    """
    manager_id, done = team[0], team[1] or 0
    start, rows = done, []
    try:
        pacer.wait()
        try:
            real = real_transfers(fetch_manager_transfers(manager_id), types)
        except FplNotFoundError:
            logger.info(
                "Team %s no longer exists; skipped to gameweek %s", manager_id, latest
            )
            done = latest
            return
        with Session(engine) as session:
            captain = team_gameweeks.last_captain(session, manager_id, done + 1)
        for event in range(done + 1, latest + 1):
            pacer.wait()
            try:
                picks = fetch_manager_picks(manager_id, event)
            except FplNotFoundError:
                if event == latest:
                    break
                done = event
                continue
            row = team_gameweeks.build(
                manager_id, event, picks, real.get(event, []), captain
            )
            rows.append(row)
            captain, done = row["captain"], event
    finally:
        if done > start:
            with Session(engine) as session, session.begin():
                team_gameweeks.save(session, manager_id, rows, done)


def run_pass(
    engine: Optional[Engine] = None, minutes: float = GAMEWEEK_PASS_MINUTES
) -> bool:
    """Run one pass and return whether it finished without an error. Stopping at
    the time limit isn't one.

    Raises SQLAlchemyError only if the run can't be recorded at all.
    """
    engine = engine or database.engine
    run_id = start_run(engine, "team_gameweeks")
    pacer = Pacer(minutes)
    status, error = "succeeded", None
    try:
        with Session(engine) as session, session.begin():
            purged = league_activity.purge(session)
            latest = league_activity.latest_event(session)
            league_ids = list(
                session.scalars(
                    select(TrackedLeague.league_id).order_by(TrackedLeague.league_id)
                )
            )
            types = dict(
                session.execute(select(Element.id, Element.element_type)).all()
            )
        if purged:
            logger.info("Stopped tracking %s idle league(s)", purged)
        if latest is not None:
            for league_id in league_ids:
                refresh_league(engine, pacer, league_id)
            with Session(engine) as session:
                teams = team_gameweeks.teams_behind(session, latest)
            for team in teams:
                pass_team(engine, pacer, team, latest, types)
            logger.info(
                "Gameweek pass: %s team(s) brought up to gameweek %s",
                len(teams),
                latest,
            )
    except TimeUp:
        logger.info("Gameweek pass stopped at its %s-minute limit", minutes)
    except SYNC_ERRORS as exc:
        status, error = "failed", describe(exc)
        logger.error("Gameweek pass stopped: %s", error)
    finish_run(engine, run_id, status, error)
    return status == "succeeded"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        with calls_from("gameweek_pass"):
            succeeded = run_pass()
    except SQLAlchemyError as exc:
        logger.error("Could not record the gameweek pass: %s", describe(exc))
        return 1
    return 0 if succeeded else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
