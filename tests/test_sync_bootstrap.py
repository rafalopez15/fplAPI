# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
import logging
from decimal import Decimal
from uuid import uuid4

import pytest
import requests
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from src.db.models import (
    Base,
    Element,
    ElementEventPoints,
    Event,
    Fixture,
    Profile,
    SyncRun,
    Team,
    TrackedTeam,
    UserTeam,
)
from src.jobs import sync_bootstrap as job
from src.util.fpl_client import FplNotFoundError, FplUnavailableError
from tests.conftest import (
    ELEMENT_TYPES,
    future_event,
    make_element,
    make_event,
    make_fixture,
    make_team,
)


@pytest.fixture
def engine(db_engine):
    """The test database. The job commits, so empty every table afterwards."""
    yield db_engine
    with db_engine.begin() as connection:
        tables = ", ".join(Base.metadata.tables)
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def bootstrap():
    """A small bootstrap-static response with FPL's raw values (decimals as strings)."""
    return {
        "teams": [
            make_team(),
            make_team(id=2, code=43, name="Man City", short_name="MCI"),
        ],
        "element_types": ELEMENT_TYPES,
        "elements": [
            make_element(id=1),
            make_element(id=2, web_name="Haaland", team=2, element_type=4, form="8.1"),
        ],
        "events": [make_event(), future_event()],
        "total_players": 11219378,
        # Not part of bootstrap-static: run() serves these from the fixtures fetch.
        "fixtures": [
            make_fixture(),
            make_fixture(id=85, event=None, kickoff_time=None),
        ],
    }


def run(engine, data):
    """Sync data, serving "fixtures" from the fixtures fetch and the rest from
    bootstrap."""
    bootstrap = {key: value for key, value in data.items() if key != "fixtures"}
    return job.sync_bootstrap(
        engine,
        fetch=lambda: bootstrap,
        fetch_fixtures_list=lambda: data.get("fixtures", []),
    )


def count(engine, model):
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model))


def sync_runs(engine):
    with Session(engine) as session:
        return session.scalars(select(SyncRun).order_by(SyncRun.id)).all()


# --- successful syncs ------------------------------------------------------


def test_first_sync_stores_everything(engine, bootstrap):
    assert run(engine, bootstrap) is True

    assert [count(engine, model) for _, model in job.COLLECTIONS] == [2, 4, 2, 2, 2]
    with Session(engine) as session:
        haaland = session.get(Element, 2)
        assert haaland.form == Decimal("8.1")
        assert haaland.can_select is True
        gameweek = session.get(Event, 9)
        assert gameweek.top_element_points == 17
        assert gameweek.chip_plays == [{"chip_name": "bboost", "num_played": 814606}]
        assert session.get(Event, 10).most_selected is None


def test_successful_run_is_recorded(engine, bootstrap):
    run(engine, bootstrap)

    [sync_run] = sync_runs(engine)
    assert (sync_run.kind, sync_run.status, sync_run.error) == (
        "bootstrap",
        "succeeded",
        None,
    )
    assert sync_run.finished_at >= sync_run.started_at


def test_resync_updates_rows_in_place(engine, bootstrap):
    run(engine, bootstrap)
    with Session(engine) as session:
        first_updated_at = session.get(Element, 1).updated_at

    bootstrap["elements"][0].update(now_cost=91, can_select=False)
    bootstrap["teams"][0]["position"] = 2
    assert run(engine, bootstrap) is True

    assert [count(engine, model) for _, model in job.COLLECTIONS] == [2, 4, 2, 2, 2]
    with Session(engine) as session:
        saka = session.get(Element, 1)
        assert (saka.now_cost, saka.can_select) == (91, False)
        assert saka.updated_at > first_updated_at
        assert session.get(Team, 1).position == 2


def test_unchanged_rows_are_not_rewritten(engine, bootstrap, caplog):
    run(engine, bootstrap)
    with Session(engine) as session:
        before = {e.id: e.updated_at for e in session.scalars(select(Element))}

    bootstrap["elements"][1]["transfers_in_event"] += 1
    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert run(engine, bootstrap) is True

    with Session(engine) as session:
        after = {e.id: e.updated_at for e in session.scalars(select(Element))}
    assert after[1] == before[1]  # identical, so skipped
    assert after[2] > before[2]  # changed, so written
    assert "Upserted 2 elements (1 new or changed)" in caplog.text
    assert "Upserted 2 teams (0 new or changed)" in caplog.text


def test_raw_strings_equal_to_stored_values_are_unchanged(engine, bootstrap):
    # FPL sends "6.0" and "2026-10-31T11:00:00Z"; Postgres stores numeric and
    # timestamptz. The comparison happens after casting, so they count as equal.
    run(engine, bootstrap)
    with Session(engine) as session:
        assert job.upsert(session, Event, [job.to_row(Event, make_event())]) == 0
        assert (
            job.upsert(session, Element, [job.to_row(Element, make_element(id=1))]) == 0
        )


def test_players_fpl_drops_are_kept(engine, bootstrap):
    run(engine, bootstrap)
    bootstrap["elements"].pop()
    run(engine, bootstrap)

    assert count(engine, Element) == 2


def test_empty_collection_is_skipped(engine, bootstrap):
    bootstrap["events"] = []
    bootstrap["fixtures"] = []  # they reference gameweeks

    assert run(engine, bootstrap) is True
    assert count(engine, Event) == 0


def test_fixtures_are_stored(engine, bootstrap):
    assert run(engine, bootstrap) is True

    with Session(engine) as session:
        fixture = session.get(Fixture, 91)
        assert (fixture.event, fixture.team_h, fixture.team_a) == (10, 2, 1)
        assert (fixture.team_h_difficulty, fixture.team_a_difficulty) == (4, 5)
        assert fixture.kickoff_time.isoformat() == "2026-11-07T15:00:00+00:00"
        postponed = session.get(Fixture, 85)
        assert (postponed.event, postponed.kickoff_time) == (None, None)


def test_finished_fixture_scores_are_updated(engine, bootstrap):
    run(engine, bootstrap)
    bootstrap["fixtures"][0].update(started=True, team_h_score=3, team_a_score=3)
    run(engine, bootstrap)
    with Session(engine) as session:
        fixture = session.get(Fixture, 91)
        assert (fixture.started, fixture.finished) == (True, False)

    bootstrap["fixtures"][0]["finished"] = True
    run(engine, bootstrap)
    with Session(engine) as session:
        fixture = session.get(Fixture, 91)
        assert (fixture.finished, fixture.team_h_score, fixture.team_a_score) == (
            True,
            3,
            3,
        )


# --- failures --------------------------------------------------------------


def test_failed_fixtures_fetch_writes_nothing(engine, bootstrap):
    def fetch_fixtures():
        raise requests.exceptions.Timeout("fixtures timed out")

    assert (
        job.sync_bootstrap(
            engine, fetch=lambda: bootstrap, fetch_fixtures_list=fetch_fixtures
        )
        is False
    )

    assert count(engine, Team) == 0
    assert sync_runs(engine)[0].error == "fixtures timed out"


def test_fixture_with_unknown_team_rolls_back_everything(engine, bootstrap):
    bootstrap["fixtures"][0]["team_a"] = 99

    assert run(engine, bootstrap) is False
    assert count(engine, Element) == 0
    assert "foreign key" in sync_runs(engine)[0].error


def test_failed_fetch_writes_nothing_and_is_recorded(engine, caplog):
    def fetch():
        raise requests.exceptions.ConnectionError("connection refused")

    assert job.sync_bootstrap(engine, fetch=fetch) is False

    assert count(engine, Team) == 0
    [sync_run] = sync_runs(engine)
    assert (sync_run.status, sync_run.error) == ("failed", "connection refused")
    assert sync_run.finished_at is not None
    assert "connection refused" in caplog.text


def test_failure_partway_through_rolls_back_everything(engine, bootstrap):
    bootstrap["elements"][1]["team"] = 99  # no such team

    assert run(engine, bootstrap) is False

    # Teams were written before elements, but the whole sync rolled back.
    assert count(engine, Team) == 0
    [sync_run] = sync_runs(engine)
    assert "foreign key" in sync_run.error
    assert len(sync_run.error) < 500  # the driver's message, not every parameter


def test_failed_sync_keeps_previous_data(engine, bootstrap):
    run(engine, bootstrap)
    bootstrap["elements"][0]["now_cost"] = 91
    bootstrap["elements"][1]["team"] = 99

    assert run(engine, bootstrap) is False

    with Session(engine) as session:
        assert session.get(Element, 1).now_cost == 90


def test_missing_required_field_fails_the_sync(engine, bootstrap):
    del bootstrap["elements"][0]["web_name"]

    assert run(engine, bootstrap) is False
    assert "web_name" in sync_runs(engine)[0].error


def test_missing_collection_fails_the_sync(engine, bootstrap):
    del bootstrap["events"]

    assert run(engine, bootstrap) is False
    assert sync_runs(engine)[0].error == "'events'"


def test_error_message_is_truncated(engine):
    def fetch():
        raise requests.exceptions.HTTPError("x" * 5000)

    job.sync_bootstrap(engine, fetch=fetch)
    assert len(sync_runs(engine)[0].error) == job.MAX_ERROR_LENGTH


# --- gameweek points --------------------------------------------------------


def finished_event(id_):
    return make_event(
        id=id_,
        name=f"Gameweek {id_}",
        is_current=False,
        finished=True,
        data_checked=True,
    )


def live(*players):
    """FPL's event/{gw}/live/ response for (id, total_points, minutes) players."""
    return {
        "elements": [
            {
                "id": id_,
                "stats": {"total_points": points, "minutes": minutes, "bps": 9},
                "explain": [],
                "modified": False,
            }
            for id_, points, minutes in players
        ]
    }


class FakeLive:
    """fetch_event_live stand-in that records which gameweeks were fetched."""

    def __init__(self, response=None, error=None):
        self.calls, self.response, self.error = [], response, error

    def __call__(self, event):
        self.calls.append(event)
        if self.error:
            raise self.error
        return self.response or live((1, 5, 90), (2, 13, 90))


@pytest.fixture
def synced(engine, bootstrap):
    """Bootstrap data with gameweek 8 finished and confirmed, 9 in progress, 10 to
    come."""
    bootstrap["events"] = [finished_event(8), make_event(), future_event()]
    run(engine, bootstrap)
    return bootstrap


def stored_points(engine):
    with Session(engine) as session:
        rows = session.scalars(
            select(ElementEventPoints).order_by(
                ElementEventPoints.event, ElementEventPoints.element
            )
        )
        return [(r.element, r.event, r.total_points, r.minutes) for r in rows]


def points_runs(engine):
    return [
        (r.event_id, r.status) for r in sync_runs(engine) if r.kind == "event_points"
    ]


@pytest.mark.usefixtures("synced")
def test_points_are_stored_for_confirmed_gameweeks_only(engine):
    fetch = FakeLive()
    assert job.sync_event_points(engine, fetch_live=fetch) is True

    assert fetch.calls == [8]  # 9 isn't confirmed yet, 10 hasn't started
    assert stored_points(engine) == [(1, 8, 5, 90), (2, 8, 13, 90)]
    assert points_runs(engine) == [(8, "succeeded")]


@pytest.mark.usefixtures("synced")
def test_stored_gameweeks_are_not_fetched_again(engine):
    job.sync_event_points(engine, fetch_live=FakeLive())
    fetch = FakeLive()
    assert job.sync_event_points(engine, fetch_live=fetch) is True
    assert not fetch.calls
    assert points_runs(engine) == [(8, "succeeded")]


def test_newly_confirmed_gameweek_is_fetched(engine, synced):
    job.sync_event_points(engine, fetch_live=FakeLive())
    synced["events"][1] = finished_event(9)
    run(engine, synced)

    fetch = FakeLive(live((1, 2, 60)))
    job.sync_event_points(engine, fetch_live=fetch)
    assert fetch.calls == [9]
    assert (1, 9, 2, 60) in stored_points(engine)


def test_backfill_fetches_every_confirmed_gameweek_in_order(engine, synced):
    synced["events"] = [finished_event(9), finished_event(8), future_event()]
    run(engine, synced)
    fetch = FakeLive()
    job.sync_event_points(engine, fetch_live=fetch)
    assert fetch.calls == [8, 9]


def test_points_failure_is_recorded_and_keeps_bootstrap_data(engine, synced, caplog):
    synced["events"] = [finished_event(8), finished_event(9), future_event()]
    run(engine, synced)
    fetch = FakeLive(error=FplUnavailableError("timed out"))

    with caplog.at_level(logging.ERROR):
        assert job.sync_event_points(engine, fetch_live=fetch) is False

    assert fetch.calls == [8]  # stops at the first failure
    assert not stored_points(engine)
    [failed] = [r for r in sync_runs(engine) if r.kind == "event_points"]
    assert (failed.event_id, failed.status, failed.error) == (8, "failed", "timed out")
    assert count(engine, Element) == 2
    assert "Gameweek 8 points sync failed: timed out" in caplog.text


@pytest.mark.usefixtures("synced")
def test_failed_gameweek_is_retried_next_run(engine):
    job.sync_event_points(
        engine, fetch_live=FakeLive(error=FplUnavailableError("down"))
    )
    fetch = FakeLive()
    assert job.sync_event_points(engine, fetch_live=fetch) is True
    assert fetch.calls == [8]
    assert points_runs(engine) == [(8, "failed"), (8, "succeeded")]


@pytest.mark.parametrize(
    "response",
    [
        live((1, 5, 90), (999, 3, 90)),  # a player bootstrap-static doesn't have
        {"oops": []},  # no elements
    ],
)
@pytest.mark.usefixtures("synced")
def test_bad_live_data_fails_the_gameweek_and_writes_nothing(engine, response):
    assert job.sync_event_points(engine, fetch_live=FakeLive(response)) is False
    assert not stored_points(engine)
    assert points_runs(engine) == [(8, "failed")]


# --- team names --------------------------------------------------------------


def add_account_teams(engine, *manager_ids):
    """Two accounts, both with every team in manager_ids, as the API would save them."""
    users = [uuid4(), uuid4()]
    with Session(engine) as session, session.begin():
        session.add_all(Profile(id=user) for user in users)
        session.flush()
        session.add_all(
            UserTeam(user_id=user, manager_id=m, relation="following")
            for user in users
            for m in manager_ids
        )


def tracked(engine):
    with Session(engine) as session:
        rows = session.execute(select(TrackedTeam.manager_id, TrackedTeam.name))
        return dict(rows.all())


class FakeManagers:
    """fetch_manager: a name per id, raising whatever errors[id] holds."""

    def __init__(self, errors=None):
        self.errors = errors or {}
        self.calls = []

    def __call__(self, manager_id):
        self.calls.append(manager_id)
        if manager_id in self.errors:
            raise self.errors[manager_id]
        return {"id": manager_id, "name": f"Team {manager_id}"}


def test_team_names_are_fetched_once_per_team(engine):
    add_account_teams(engine, 3, 1, 2)
    fetch = FakeManagers()
    assert job.sync_team_names(engine, fetch=fetch) is True
    assert fetch.calls == [1, 2, 3]  # each once, though two accounts have them
    assert tracked(engine) == {1: "Team 1", 2: "Team 2", 3: "Team 3"}


def test_known_teams_are_skipped(engine):
    add_account_teams(engine, 1, 2)
    job.sync_team_names(engine, fetch=FakeManagers())
    fetch = FakeManagers()
    assert job.sync_team_names(engine, fetch=fetch) is True
    assert not fetch.calls


def test_a_team_fpl_doesnt_have_is_stored_without_a_name(engine):
    add_account_teams(engine, 1, 2)
    fetch = FakeManagers({1: FplNotFoundError("gone")})
    assert job.sync_team_names(engine, fetch=fetch) is True
    assert tracked(engine) == {1: None, 2: "Team 2"}
    # Not asked for again.
    again = FakeManagers()
    job.sync_team_names(engine, fetch=again)
    assert not again.calls


def test_fpl_failing_stops_until_the_next_run(engine, caplog):
    add_account_teams(engine, 1, 2, 3)
    fetch = FakeManagers({2: FplUnavailableError("down")})
    with caplog.at_level(logging.ERROR):
        assert job.sync_team_names(engine, fetch=fetch) is False
    assert fetch.calls == [1, 2]
    assert tracked(engine) == {1: "Team 1"}  # what it got before stopping is kept
    assert "Team name sync stopped at team 2: down" in caplog.text
    job.sync_team_names(engine, fetch=FakeManagers())
    assert tracked(engine) == {1: "Team 1", 2: "Team 2", 3: "Team 3"}


def test_team_names_are_fetched_in_batches(engine, monkeypatch):
    monkeypatch.setattr(job, "NAME_BATCH", 2)
    add_account_teams(engine, 1, 2, 3)
    fetch = FakeManagers()
    job.sync_team_names(engine, fetch=fetch)
    assert fetch.calls == [1, 2]
    job.sync_team_names(engine, fetch=fetch)
    assert fetch.calls == [1, 2, 3]


def test_no_teams_on_accounts_makes_no_calls(engine):
    fetch = FakeManagers()
    assert job.sync_team_names(engine, fetch=fetch) is True
    assert not fetch.calls


# --- main ------------------------------------------------------------------


@pytest.fixture
def steps(monkeypatch):
    """main()'s three steps, each succeeding unless a test changes it."""
    ran = []
    for name in ("sync_bootstrap", "sync_event_points", "sync_team_names"):
        monkeypatch.setattr(job, name, lambda name=name: ran.append(name) or True)
    return ran


@pytest.mark.usefixtures("steps")
@pytest.mark.parametrize(
    "failing, exit_code",
    [
        (None, 0),
        ("sync_bootstrap", 1),
        ("sync_event_points", 1),
        ("sync_team_names", 1),
    ],
)
def test_main_exit_code(monkeypatch, failing, exit_code):
    if failing:
        monkeypatch.setattr(job, failing, lambda: False)
    assert job.main() == exit_code


def test_main_runs_every_step_even_when_bootstrap_fails(monkeypatch, steps):
    monkeypatch.setattr(job, "sync_bootstrap", lambda: False)
    job.main()
    assert steps == ["sync_event_points", "sync_team_names"]


def test_main_fails_when_the_run_cant_be_recorded(monkeypatch, caplog):
    def unreachable():
        raise OperationalError("INSERT", {}, Exception("connection refused"))

    monkeypatch.setattr(job, "sync_bootstrap", unreachable)
    with caplog.at_level(logging.ERROR):
        assert job.main() == 1
    assert "Could not record the sync run: connection refused" in caplog.text
