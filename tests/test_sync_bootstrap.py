# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
import logging
from decimal import Decimal

import pytest
import requests
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from src.db.models import Base, Element, Event, SyncRun, Team
from src.jobs import sync_bootstrap as job
from tests.conftest import make_element


@pytest.fixture
def engine(db_engine):
    """The test database. The job commits, so empty every table afterwards."""
    yield db_engine
    with db_engine.begin() as connection:
        tables = ", ".join(Base.metadata.tables)
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


def make_team(**overrides):
    team = {
        "id": 1, "code": 3, "name": "Arsenal", "short_name": "ARS", "position": 1,
        "played": 9, "win": 7, "draw": 1, "loss": 1, "points": 22, "strength": None,
        "strength_overall_home": 1300, "strength_overall_away": 1320,
        "strength_attack_home": 1250, "strength_attack_away": 1290,
        "strength_defence_home": 1340, "strength_defence_away": 1350,
        # Fields FPL sends that aren't columns.
        "form": None, "pulse_id": 1, "unavailable": False,
    }
    team.update(overrides)
    return team


def make_element_type(id_, name):
    return {
        "id": id_, "singular_name": name, "singular_name_short": name[:3].upper(),
        "plural_name": f"{name}s", "plural_name_short": name[:3].upper(),
        "squad_select": 5, "squad_min_play": 1, "squad_max_play": 5,
        "element_count": 100, "ui_shirt_specific": False,
    }


def make_event(**overrides):
    event = {
        "id": 9, "name": "Gameweek 9", "deadline_time": "2026-10-31T11:00:00Z",
        "deadline_time_epoch": 1793444400, "deadline_time_game_offset": 0,
        "release_time": None, "finished": False, "data_checked": False,
        "is_previous": False, "is_current": True, "is_next": False,
        "average_entry_score": 52, "highest_score": 127, "highest_scoring_entry": 12345,
        "transfers_made": 9000000, "most_selected": 1, "most_transferred_in": 2,
        "most_captained": 2, "most_vice_captained": 1, "top_element": 2,
        "top_element_info": {"id": 2, "points": 17},
        "chip_plays": [{"chip_name": "bboost", "num_played": 814606}],
        "can_enter": False,
    }
    event.update(overrides)
    return event


def future_event():
    return make_event(
        id=10, name="Gameweek 10", deadline_time="2026-11-07T13:30:00Z",
        deadline_time_epoch=1794058200, is_current=False, is_next=True,
        average_entry_score=0, highest_score=None, highest_scoring_entry=None,
        most_selected=None, most_transferred_in=None, most_captained=None,
        most_vice_captained=None, top_element=None, top_element_info=None, chip_plays=[],
    )


@pytest.fixture
def bootstrap():
    """A small bootstrap-static response with FPL's raw values (decimals as strings)."""
    return {
        "teams": [make_team(), make_team(id=2, code=43, name="Man City", short_name="MCI")],
        "element_types": [
            make_element_type(id_, name)
            for id_, name in enumerate(["Goalkeeper", "Defender", "Midfielder", "Forward"], 1)
        ],
        "elements": [
            make_element(id=1),
            make_element(id=2, web_name="Haaland", team=2, element_type=4, form="8.1"),
        ],
        "events": [make_event(), future_event()],
        "total_players": 11219378,
    }


def run(engine, data):
    return job.sync_bootstrap(engine, fetch=lambda: data)


def count(engine, model):
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model))


def sync_runs(engine):
    with Session(engine) as session:
        return session.scalars(select(SyncRun).order_by(SyncRun.id)).all()


# --- successful syncs ------------------------------------------------------

def test_first_sync_stores_everything(engine, bootstrap):
    assert run(engine, bootstrap) is True

    assert [count(engine, model) for _, model in job.COLLECTIONS] == [2, 4, 2, 2]
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
    assert (sync_run.kind, sync_run.status, sync_run.error) == ("bootstrap", "succeeded", None)
    assert sync_run.finished_at >= sync_run.started_at


def test_resync_updates_rows_in_place(engine, bootstrap):
    run(engine, bootstrap)
    with Session(engine) as session:
        first_updated_at = session.get(Element, 1).updated_at

    bootstrap["elements"][0].update(now_cost=91, can_select=False)
    bootstrap["teams"][0]["position"] = 2
    assert run(engine, bootstrap) is True

    assert [count(engine, model) for _, model in job.COLLECTIONS] == [2, 4, 2, 2]
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
        assert job.upsert(session, Element, [job.to_row(Element, make_element(id=1))]) == 0


def test_players_fpl_drops_are_kept(engine, bootstrap):
    run(engine, bootstrap)
    bootstrap["elements"].pop()
    run(engine, bootstrap)

    assert count(engine, Element) == 2


def test_empty_collection_is_skipped(engine, bootstrap):
    bootstrap["events"] = []

    assert run(engine, bootstrap) is True
    assert count(engine, Event) == 0


# --- failures --------------------------------------------------------------

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


# --- main ------------------------------------------------------------------

@pytest.mark.parametrize("succeeded, exit_code", [(True, 0), (False, 1)])
def test_main_exit_code(monkeypatch, succeeded, exit_code):
    monkeypatch.setattr(job, "sync_bootstrap", lambda: succeeded)
    assert job.main() == exit_code


def test_main_fails_when_the_run_cant_be_recorded(monkeypatch, caplog):
    def unreachable():
        raise OperationalError("INSERT", {}, Exception("connection refused"))

    monkeypatch.setattr(job, "sync_bootstrap", unreachable)
    with caplog.at_level(logging.ERROR):
        assert job.main() == 1
    assert "Could not record the sync run: connection refused" in caplog.text
