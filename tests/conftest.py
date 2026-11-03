# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
import os

# Config is read at import time, so make sure it exists before importing src.
# This keeps the suite independent of a local .env file (e.g. in CI).
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")

from pathlib import Path  # pylint: disable=wrong-import-position

import pytest  # pylint: disable=wrong-import-position
from alembic import command  # pylint: disable=wrong-import-position
from alembic.config import Config  # pylint: disable=wrong-import-position
from fastapi.testclient import TestClient  # pylint: disable=wrong-import-position
from sqlalchemy import create_engine, func  # pylint: disable=wrong-import-position
from sqlalchemy.orm import Session  # pylint: disable=wrong-import-position
from main import app  # pylint: disable=wrong-import-position
from src.db.models import (  # pylint: disable=wrong-import-position
    Element,
    ElementType,
    Event,
    Fixture,
    SyncRun,
    Team,
)
from src.jobs.sync_bootstrap import to_row  # pylint: disable=wrong-import-position
from src.util import database  # pylint: disable=wrong-import-position


def make_element(**overrides):
    element = {
        "id": 1,
        "code": 223340,
        "first_name": "Bukayo",
        "second_name": "Saka",
        "web_name": "Saka",
        "element_type": 3,
        "team": 1,
        "team_code": 3,
        "photo": "223340.jpg",
        "status": "a",
        "news": "",
        "news_added": None,
        "chance_of_playing_next_round": None,
        "chance_of_playing_this_round": None,
        "can_select": True,
        "can_transact": True,
        "removed": False,
        "now_cost": 90,
        "cost_change_event": 0,
        "cost_change_start": 2,
        "selected_by_percent": "40.1",
        "transfers_in_event": 13365,
        "transfers_out_event": 2478,
        "total_points": 120,
        "event_points": 5,
        "points_per_game": "5.5",
        "form": "6.0",
        "ep_next": "5.8",
        "minutes": 720,
        "starts": 8,
        "goals_scored": 4,
        "assists": 3,
        "clean_sheets": 2,
        "goals_conceded": 7,
        "saves": 0,
        "bonus": 6,
        "yellow_cards": 1,
        "red_cards": 0,
        "expected_goals": "3.21",
        "expected_assists": "2.45",
        "expected_goal_involvements": "5.66",
        "expected_goals_conceded": "6.18",
        "ict_index": "98.7",
        # A field FPL sends that ElementResponse leaves out.
        "influence_rank": 12,
    }
    element.update(overrides)
    return element


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


ELEMENT_TYPES = [
    make_element_type(id_, name)
    for id_, name in enumerate(["Goalkeeper", "Defender", "Midfielder", "Forward"], 1)
]


def make_event(**overrides):
    """The current gameweek, as FPL sends it."""
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
    """A gameweek that hasn't been played, so FPL sends null stats."""
    return make_event(
        id=10, name="Gameweek 10", deadline_time="2026-11-07T13:30:00Z",
        deadline_time_epoch=1794058200, is_current=False, is_next=True,
        average_entry_score=0, highest_score=None, highest_scoring_entry=None,
        most_selected=None, most_transferred_in=None, most_captained=None,
        most_vice_captained=None, top_element=None, top_element_info=None, chip_plays=[],
    )


def make_fixture(**overrides):
    """An upcoming match, as FPL's /fixtures/ endpoint sends it."""
    fixture = {
        "id": 91, "code": 2561986, "event": 10, "team_h": 2, "team_a": 1,
        "team_h_difficulty": 4, "team_a_difficulty": 5,
        "kickoff_time": "2026-11-07T15:00:00Z", "started": False, "finished": False,
        "team_h_score": None, "team_a_score": None,
        # Fields FPL sends that aren't columns.
        "finished_provisional": False, "minutes": 0, "provisional_start_time": False,
        "stats": [], "pulse_id": 124881,
    }
    fixture.update(overrides)
    return fixture


def make_fpl_manager(**overrides):
    """FPL's entry/{id}/ response, including fields ManagerResponse leaves out."""
    manager = {
        "id": 1, "name": "Solio Moose", "player_first_name": "Chris",
        "player_last_name": "Musson", "current_event": 9, "started_event": 1,
        "favourite_team": 14, "player_region_name": "England",
        "summary_overall_points": 563, "summary_overall_rank": 1571477,
        "summary_event_points": 55, "summary_event_rank": 1972509,
        "last_deadline_bank": 21, "last_deadline_value": 1022,
        "last_deadline_total_transfers": 6,
        # Left out of the response.
        "joined_time": "2026-07-18T09:12:45.123456Z", "player_region_id": 241,
        "leagues": {"classic": [{"id": 314, "name": "Overall"}], "h2h": [], "cup": {}},
        "kit": None, "club_badge_src": None, "entered_events": [1, 2, 3],
    }
    manager.update(overrides)
    return manager


def make_fpl_transfers():
    """FPL's entry/{id}/transfers/ response: newest first, with fractional seconds."""
    return [
        {"element_in": 566, "element_in_cost": 50, "element_out": 114,
         "element_out_cost": 45, "entry": 1, "event": 9,
         "time": "2026-10-31T10:08:30.794468Z"},
        {"element_in": 2, "element_in_cost": 145, "element_out": 351,
         "element_out_cost": 120, "entry": 1, "event": 4,
         "time": "2026-09-12T18:01:02.000001Z"},
    ]


def make_fpl_history():
    """FPL's entry/{id}/history/ response, including fields HistoryResponse leaves out."""
    gameweek = {
        "event": 1, "points": 72, "total_points": 72, "rank": 1203411,
        "overall_rank": 1203411, "bank": 5, "value": 1000, "event_transfers": 0,
        "event_transfers_cost": 0, "points_on_bench": 8,
        # Left out of the response.
        "rank_sort": 1203500, "percentile_rank": 15, "overall_rank_percentage": 12,
    }
    return {
        "current": [gameweek, {**gameweek, "event": 2, "points": 51, "total_points": 123}],
        "chips": [{"name": "bboost", "time": "2026-08-28T17:25:01.123184Z", "event": 2}],
        "past": [{"season_name": "2024/25", "total_points": 2301, "rank": 150234,
                  "rank_percentage": "2"}],
    }



def make_fpl_picks(event=9, active_chip=None):
    """FPL's entry/{id}/event/{gw}/picks/ response: 11 starters (captain at position
    5, vice at 6), 4 on the bench, one automatic sub, and fields PicksResponse leaves
    out.
    """
    element_types = [1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 1, 2, 3, 4]
    picks = [
        {"element": 100 + position, "position": position,
         "multiplier": 0 if position > 11 else 1, "is_captain": False,
         "is_vice_captain": False, "element_type": element_type}
        for position, element_type in enumerate(element_types, start=1)
    ]
    picks[4].update(multiplier=3 if active_chip == "3xc" else 2, is_captain=True)
    picks[5]["is_vice_captain"] = True
    return {
        "active_chip": active_chip,
        "automatic_subs": [{"entry": 1, "element_in": 113, "element_out": 103,
                            "event": event}],
        "entry_history": {
            "event": event, "points": 55, "total_points": 563, "rank": 2551066,
            "overall_rank": 1673563, "bank": 21, "value": 1022, "event_transfers": 3,
            "event_transfers_cost": 0, "points_on_bench": 13,
            # Left out of the response.
            "rank_sort": 2551066, "percentile_rank": 25, "overall_rank_percentage": "15",
        },
        "picks": picks,
    }

SEEDED_FIXTURES = [
    # Listed out of kickoff order, the way FPL's list can be.
    make_fixture(),  # 91: gameweek 10, 7 Nov
    make_fixture(id=71, event=8, team_h=1, team_a=2, team_h_difficulty=5,
                 team_a_difficulty=4, kickoff_time="2026-10-25T15:00:00Z",
                 started=True, finished=True, team_h_score=2, team_a_score=1),
    make_fixture(id=85, event=None, kickoff_time=None),  # postponed, not rescheduled
    # Played, but FPL hasn't confirmed bonus points, so not finished yet.
    make_fixture(id=95, event=9, kickoff_time="2026-11-01T16:30:00Z",
                 started=True, team_h_score=0, team_a_score=1),
]


@pytest.fixture
def seeded_session(db_session):
    """The test database with a small synced dataset, as the bootstrap sync writes it:
    2 teams, 4 positions, 3 players, gameweeks 8 to 10, 4 fixtures (71 finished,
    95 played but not yet finished, 91 upcoming, 85 postponed) and a successful
    sync run.
    """
    data = [
        (Team, [make_team(), make_team(id=2, code=43, name="Man City", short_name="MCI")]),
        (ElementType, ELEMENT_TYPES),
        (Element, [
            make_element(id=1),
            make_element(id=2, web_name="Haaland", team=2, element_type=4, form="8.1"),
            make_element(id=3, web_name="Palmer"),
        ]),
        (Event, [
            make_event(id=8, name="Gameweek 8", is_current=False, is_previous=True,
                       finished=True, data_checked=True),
            make_event(),
            future_event(),
        ]),
        (Fixture, SEEDED_FIXTURES),
    ]
    for model, items in data:
        db_session.add_all(model(**to_row(model, item)) for item in items)
        db_session.flush()
    db_session.add(SyncRun(kind="bootstrap", status="succeeded", finished_at=func.now()))
    db_session.flush()
    return db_session


@pytest.fixture
def client(seeded_session):
    """A TestClient whose requests use the seeded test database.

    Not used as a context manager, so the app's startup events don't run.
    """
    app.dependency_overrides[database.get_session] = lambda: seeded_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Fail loudly if any test reaches the real FPL API."""

    def _blocked(*args, **kwargs):
        raise AssertionError(f"Unexpected network call: {args} {kwargs}")

    monkeypatch.setattr("src.util.fpl_client.requests.get", _blocked)


@pytest.fixture(autouse=True)
def block_database(monkeypatch):
    """Fail loudly if any test opens a real database connection."""

    def _blocked(*args, **kwargs):
        raise AssertionError(f"Unexpected database connection: {args} {kwargs}")

    monkeypatch.setattr(database.engine, "connect", _blocked)


# --- test database ---------------------------------------------------------

def alembic_config(url: str) -> Config:
    """Alembic config for the test database.

    Built without alembic.ini so env.py skips fileConfig, which would disable the
    app's loggers for the rest of the run.
    """
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).parents[1] / "migrations")
    )
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


@pytest.fixture(scope="session")
def test_database_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "TEST_DATABASE_URL isn't set. Start the test database first; see "
            "'Tests and linting' in the README."
        )
    if "supabase" in url:
        pytest.fail("TEST_DATABASE_URL points at Supabase. Tests must use a local database.")
    return url


@pytest.fixture(scope="session")
def db_engine(test_database_url):
    """An engine for the test database, migrated from scratch once per run."""
    config = alembic_config(test_database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """A session whose changes are rolled back after the test, even after commit()."""
    with db_engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()
