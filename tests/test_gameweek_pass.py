# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""The gameweek pass: what each team in a tracked league did each gameweek."""

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from src.db.models import (
    Base,
    Element,
    ElementType,
    Event,
    LeagueTeam,
    SyncRun,
    Team,
    TeamGameweek,
    TrackedLeague,
    TrackedTeam,
)
from src.jobs import gameweek_pass as job
from src.jobs.sync_bootstrap import to_row
from src.util import fpl_client, fpl_metrics
from src.util.fpl_client import FplNotFoundError, FplUnavailableError
from tests.conftest import (
    ELEMENT_TYPES,
    make_element,
    make_event,
    make_fpl_league_standings,
    make_fpl_manager,
    make_fpl_new_entry,
    make_fpl_picks,
    make_fpl_standing,
    make_team,
)

LEAGUE = 5508
TEAM_A, TEAM_B = 7700093, 1
MID, FWD = 3, 4


@pytest.fixture
def engine(db_engine):
    """The test database with gameweeks 1-3 past their deadline and 4 to come. The
    pass commits, so every table is emptied afterwards."""
    now = datetime.now(timezone.utc)
    with Session(db_engine) as session, session.begin():
        session.add(Team(**to_row(Team, make_team())))
        session.flush()
        session.add_all(ElementType(**to_row(ElementType, t)) for t in ELEMENT_TYPES)
        session.flush()
        session.add_all(
            Element(**to_row(Element, make_element(id=id_, element_type=type_)))
            for id_, type_ in [
                (10, MID),
                (11, MID),
                (12, MID),
                (20, FWD),
                (21, FWD),
                (22, FWD),
            ]
        )
        session.add_all(
            Event(
                **to_row(
                    Event,
                    make_event(
                        id=event,
                        name=f"Gameweek {event}",
                        deadline_time=(now + timedelta(days=7 * (event - 3) - 1)),
                    ),
                )
            )
            for event in range(1, 5)
        )
    yield db_engine
    with db_engine.begin() as connection:
        tables = ", ".join(Base.metadata.tables)
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


class Clock:
    """Stands in for the time module: sleeping and each FPL call move it on."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(job, "time", fake)
    return fake


def picks(event, captain=105, vice=106, cost=0, chip=None):
    """make_fpl_picks with the captain, vice-captain, hit and chip given."""
    result = make_fpl_picks(event=event, active_chip=chip)
    for pick in result["picks"]:
        pick["is_captain"] = pick["element"] == captain
        pick["is_vice_captain"] = pick["element"] == vice
    result["entry_history"]["event_transfers_cost"] = cost
    return result


def transfer(element_in, element_out, event, minute=0):
    return {
        "element_in": element_in,
        "element_out": element_out,
        "event": event,
        "entry": 1,
        "element_in_cost": 50,
        "element_out_cost": 45,
        "time": f"2026-10-{event:02d}T10:{minute:02d}:00.000000Z",
    }


class Fpl:
    """FPL for the pass: standings per league, and each team's entry, transfers and
    picks. Teams start in gameweek 1 and keep the same captain unless a test says
    otherwise. Every call moves the clock on by a second."""

    def __init__(self, clock):
        self.clock = clock
        self.standings = {
            LEAGUE: make_fpl_league_standings(
                results=[
                    make_fpl_standing(TEAM_A, "Amos's Team", 1),
                    make_fpl_standing(TEAM_B, "Solio Moose", 2),
                ]
            )
        }
        self.started = {}  # manager_id -> started_event
        self.transfers = {}
        self.picks = {}
        self.errors = {}  # (kind, *args) -> exception
        self.calls = []

    def _call(self, key):
        self.calls.append(key)
        self.clock.now += 1
        if key in self.errors:
            raise self.errors[key]

    def league(self, league_id, page):
        self._call(("standings", league_id))
        assert page == 1
        if league_id not in self.standings:
            raise FplNotFoundError(league_id)
        return self.standings[league_id]

    def team(self, manager_id):
        self._call(("entry", manager_id))
        return make_fpl_manager(
            id=manager_id, started_event=self.started.get(manager_id, 1)
        )

    def team_transfers(self, manager_id):
        self._call(("transfers", manager_id))
        return self.transfers.get(manager_id, [])

    def team_picks(self, manager_id, event):
        self._call(("picks", manager_id, event))
        return self.picks.get((manager_id, event)) or picks(event)


@pytest.fixture
def fpl(monkeypatch, clock):
    fake = Fpl(clock)
    monkeypatch.setattr(fpl_client, "fetch_league_standings", fake.league)
    monkeypatch.setattr(job, "fetch_manager", fake.team)
    monkeypatch.setattr(job, "fetch_manager_transfers", fake.team_transfers)
    monkeypatch.setattr(job, "fetch_manager_picks", fake.team_picks)
    return fake


def track(engine, league_id=LEAGUE, idle=timedelta(0)):
    with Session(engine) as session, session.begin():
        session.add(
            TrackedLeague(
                league_id=league_id,
                last_requested_at=datetime.now(timezone.utc) - idle,
            )
        )


def stored(engine):
    """{(manager_id, event): row} for every team_gameweeks row."""
    with Session(engine) as session:
        return {
            (row.manager_id, row.event): row
            for row in session.scalars(select(TeamGameweek))
        }


def last_events(engine):
    with Session(engine) as session:
        return dict(
            session.execute(
                select(TrackedTeam.manager_id, TrackedTeam.last_event)
            ).all()
        )


def runs(engine):
    with Session(engine) as session:
        return [
            (run.kind, run.status, run.error)
            for run in session.scalars(select(SyncRun).order_by(SyncRun.id))
        ]


# --- a new league --------------------------------------------------------------


def test_a_new_league_is_backfilled(engine, fpl):
    track(engine)

    assert job.run_pass(engine) is True

    assert sorted(stored(engine)) == [
        (team, event) for team in (TEAM_B, TEAM_A) for event in (1, 2, 3)
    ]
    assert last_events(engine) == {TEAM_A: 3, TEAM_B: 3}
    with Session(engine) as session:
        assert session.scalar(select(TrackedLeague.teams_updated_at)) is not None
        names = dict(
            session.execute(select(TrackedTeam.manager_id, TrackedTeam.name)).all()
        )
    assert names == {TEAM_A: "Amos's Team", TEAM_B: "Solio Moose"}
    # Entry and transfers once per team, then picks for each gameweek.
    assert fpl.calls.count(("entry", TEAM_A)) == 1
    assert fpl.calls.count(("transfers", TEAM_A)) == 1
    assert [c for c in fpl.calls if c[:2] == ("picks", TEAM_A)] == [
        ("picks", TEAM_A, event) for event in (1, 2, 3)
    ]
    assert runs(engine) == [("team_gameweeks", "succeeded", None)]


def test_new_entries_are_league_teams_too(engine, fpl):
    fpl.standings[LEAGUE] = make_fpl_league_standings(
        results=[], new_entries=[make_fpl_new_entry(8533420, "Kt")]
    )
    track(engine)
    job.run_pass(engine)
    assert last_events(engine) == {8533420: 3}


@pytest.mark.usefixtures("fpl")
def test_a_quiet_gameweek_still_gets_a_row(engine):
    track(engine)
    job.run_pass(engine)
    row = stored(engine)[(TEAM_A, 2)]
    assert (row.transfers, row.transfers_cost, row.chip) == ([], 0, None)
    assert (row.captain, row.vice_captain, row.captain_changed) == (105, 106, False)


# --- what's stored ---------------------------------------------------------------


def test_transfers_hit_chip_and_captain(engine, fpl):
    fpl.transfers[TEAM_A] = [transfer(12, 11, 2, minute=1), transfer(10, 12, 3)]
    fpl.picks[(TEAM_A, 2)] = picks(2, captain=107, vice=105, cost=4)
    fpl.picks[(TEAM_A, 3)] = picks(3, captain=107, chip="3xc")
    track(engine)

    job.run_pass(engine)

    rows = stored(engine)
    first, second, third = (rows[(TEAM_A, event)] for event in (1, 2, 3))
    assert (first.captain, first.captain_changed) == (105, None)
    assert second.transfers == [{"element_in": 12, "element_out": 11}]
    assert (second.transfers_cost, second.captain, second.vice_captain) == (4, 107, 105)
    assert second.captain_changed is True
    assert (third.chip, third.captain_changed) == ("3xc", False)


def test_wildcard_churn_is_reduced_to_the_real_changes(engine, fpl):
    # A Wildcard in gameweek 2: four swaps tried, really MID 12 in for MID 11 and
    # FWD 22 in for FWD 21.
    fpl.transfers[TEAM_A] = [
        transfer(22, 10, 2, minute=4),
        transfer(12, 20, 2, minute=3),
        transfer(20, 21, 2, minute=2),
        transfer(10, 11, 2, minute=1),
    ]
    fpl.picks[(TEAM_A, 2)] = picks(2, chip="wildcard")
    track(engine)

    job.run_pass(engine)

    row = stored(engine)[(TEAM_A, 2)]
    assert row.chip == "wildcard"
    assert sorted((t["element_in"], t["element_out"]) for t in row.transfers) == [
        (12, 11),
        (22, 21),
    ]


def test_a_gameweek_set_back_is_passed_again_against_the_one_before(engine, fpl):
    track(engine)
    job.run_pass(engine)
    with Session(engine) as session, session.begin():
        session.execute(
            update(TrackedTeam)
            .where(TrackedTeam.manager_id == TEAM_B)
            .values(last_event=2)
        )
    fpl.picks[(TEAM_B, 3)] = picks(3, captain=110)

    job.run_pass(engine)

    row = stored(engine)[(TEAM_B, 3)]
    assert (row.captain, row.captain_changed) == (110, True)


# --- gameweeks a team doesn't have -----------------------------------------------


def test_a_backfill_starts_at_the_gameweek_the_team_started(engine, fpl):
    fpl.started[TEAM_A] = 2
    track(engine)
    job.run_pass(engine)
    assert [c for c in fpl.calls if c[:2] == ("picks", TEAM_A)] == [
        ("picks", TEAM_A, 2),
        ("picks", TEAM_A, 3),
    ]
    assert sorted(e for t, e in stored(engine) if t == TEAM_A) == [2, 3]
    assert stored(engine)[(TEAM_A, 2)].captain_changed is None


def test_a_team_created_after_the_latest_deadline_is_done_at_once(engine, fpl):
    # It has no picks for gameweek 3 and never will, so it mustn't wait for them.
    fpl.started[TEAM_A] = 4
    track(engine)

    job.run_pass(engine)

    assert ("picks", TEAM_A, 3) not in fpl.calls
    assert last_events(engine)[TEAM_A] == 3
    assert not [key for key in stored(engine) if key[0] == TEAM_A]
    fpl.calls.clear()
    job.run_pass(engine)
    assert [c for c in fpl.calls if c[0] != "standings"] == []


def test_a_picks_404_before_the_latest_gameweek_is_skipped(engine, fpl):
    fpl.errors[("picks", TEAM_A, 1)] = FplNotFoundError("picks")
    track(engine)
    job.run_pass(engine)
    assert sorted(e for t, e in stored(engine) if t == TEAM_A) == [2, 3]
    assert stored(engine)[(TEAM_A, 2)].captain_changed is None
    assert last_events(engine)[TEAM_A] == 3


def test_unpublished_picks_for_the_latest_gameweek_wait_for_the_next_run(engine, fpl):
    fpl.errors[("picks", TEAM_A, 3)] = FplNotFoundError("picks")
    track(engine)
    job.run_pass(engine)
    assert last_events(engine)[TEAM_A] == 2

    del fpl.errors[("picks", TEAM_A, 3)]
    job.run_pass(engine)
    assert last_events(engine)[TEAM_A] == 3
    assert (TEAM_A, 3) in stored(engine)


@pytest.mark.parametrize("kind", ["entry", "transfers"])
def test_a_team_fpl_no_longer_has_is_skipped_to_the_latest_gameweek(engine, fpl, kind):
    fpl.errors[(kind, TEAM_A)] = FplNotFoundError(kind)
    track(engine)
    job.run_pass(engine)
    assert last_events(engine)[TEAM_A] == 3
    assert not [key for key in stored(engine) if key[0] == TEAM_A]


# --- stopping and carrying on ----------------------------------------------------


def test_the_time_limit_stops_the_pass_and_the_next_run_finishes(engine, fpl, clock):
    track(engine)
    # Each call takes a second here: the standings, team 1's entry, transfers and
    # picks for gameweeks 1-3, then team 7700093's entry, transfers and gameweek 1
    # picks before the limit at 9 seconds.
    assert job.run_pass(engine, minutes=9 / 60) is True
    assert last_events(engine)[TEAM_B] == 3
    assert last_events(engine)[TEAM_A] == 1

    clock.now = 0
    fpl.calls.clear()
    assert job.run_pass(engine) is True
    assert last_events(engine) == {TEAM_A: 3, TEAM_B: 3}
    # Carries on from gameweek 2, not from the start, and needs no entry call.
    assert ("entry", TEAM_A) not in fpl.calls
    assert ("picks", TEAM_A, 1) not in fpl.calls
    assert runs(engine) == [("team_gameweeks", "succeeded", None)] * 2


def test_fpl_down_stops_the_pass_until_the_next_run(engine, fpl, caplog):
    fpl.errors[("picks", TEAM_A, 2)] = FplUnavailableError("503 Service Unavailable")
    track(engine)

    with caplog.at_level(logging.ERROR):
        assert job.run_pass(engine) is False

    # Gameweek 1 is kept; nothing after the failure was tried.
    assert last_events(engine)[TEAM_A] == 1
    assert fpl.calls[-1] == ("picks", TEAM_A, 2)
    assert runs(engine) == [("team_gameweeks", "failed", "503 Service Unavailable")]
    assert "Gameweek pass stopped: 503" in caplog.text

    del fpl.errors[("picks", TEAM_A, 2)]
    assert job.run_pass(engine) is True
    assert last_events(engine)[TEAM_A] == 3


def test_fpl_down_for_a_league_stops_the_pass(engine, fpl):
    fpl.errors[("standings", LEAGUE)] = FplUnavailableError("updating")
    track(engine)
    assert job.run_pass(engine) is False
    assert not stored(engine)


def test_calls_are_paced(engine, fpl, clock):
    # Calls here take a second, so none waits; without that, each would.
    track(engine)
    job.run_pass(engine)
    assert not clock.sleeps

    fpl.clock = Clock()  # calls now take no time
    with Session(engine) as session, session.begin():
        session.execute(update(TrackedTeam).values(last_event=2))
    job.run_pass(engine)
    assert clock.sleeps and all(s == pytest.approx(job.PACE) for s in clock.sleeps)


def test_nothing_to_do_before_the_first_deadline(engine, fpl):
    with Session(engine) as session, session.begin():
        session.execute(
            update(Event).values(
                deadline_time=datetime.now(timezone.utc) + timedelta(days=1)
            )
        )
    track(engine)
    assert job.run_pass(engine) is True
    assert not fpl.calls


# --- leagues ---------------------------------------------------------------------


def test_leagues_idle_for_two_weeks_stop_being_tracked(engine, fpl, caplog):
    track(engine)
    job.run_pass(engine)
    with Session(engine) as session, session.begin():
        session.execute(
            update(TrackedLeague).values(
                last_requested_at=datetime.now(timezone.utc) - timedelta(days=15)
            )
        )
    track(engine, league_id=314, idle=timedelta(days=13))
    fpl.standings[314] = make_fpl_league_standings(results=[])

    with caplog.at_level(logging.INFO):
        job.run_pass(engine)

    with Session(engine) as session:
        assert list(session.scalars(select(TrackedLeague.league_id))) == [314]
        assert not session.scalars(select(LeagueTeam)).all()
    # What was stored stays.
    assert len(stored(engine)) == 6
    assert "Stopped tracking 1 idle league(s)" in caplog.text


@pytest.mark.usefixtures("fpl")
def test_a_league_fpl_no_longer_has_stops_being_tracked(engine):
    track(engine, league_id=999)
    assert job.run_pass(engine) is True
    with Session(engine) as session:
        assert not session.scalars(select(TrackedLeague)).all()


def test_a_team_that_left_the_league_is_no_longer_passed(engine, fpl):
    track(engine)
    job.run_pass(engine, minutes=1 / 60)  # only the standings
    fpl.standings[LEAGUE] = make_fpl_league_standings(
        results=[make_fpl_standing(TEAM_B, "Solio Moose", 1)]
    )
    job.run_pass(engine)
    with Session(engine) as session:
        assert list(session.scalars(select(LeagueTeam.manager_id))) == [TEAM_B]
    assert last_events(engine)[TEAM_A] is None


# --- main ------------------------------------------------------------------------


@pytest.mark.parametrize("succeeded, code", [(True, 0), (False, 1)])
def test_main(monkeypatch, succeeded, code):
    callers = []

    def run():
        # pylint: disable-next=protected-access
        callers.append(fpl_metrics._caller()[0])
        return succeeded

    monkeypatch.setattr(job, "run_pass", run)
    assert job.main() == code
    assert callers == ["gameweek_pass"]


def test_main_fails_when_the_run_cant_be_recorded(monkeypatch, caplog):
    def unreachable():
        raise OperationalError("INSERT", {}, Exception("connection refused"))

    monkeypatch.setattr(job, "run_pass", unreachable)
    with caplog.at_level(logging.ERROR):
        assert job.main() == 1
    assert "Could not record the gameweek pass: connection refused" in caplog.text
