# pytest fixtures are injected as same-named arguments, and the rows below repeat
# conftest's FPL data as ORM objects on purpose.
# pylint: disable=redefined-outer-name,duplicate-code
from datetime import datetime
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from src.db.models import (
    Base,
    Element,
    ElementType,
    Event,
    PlayerFixtureHistory,
    SyncRun,
    Team,
)
from tests.conftest import alembic_config, make_element


def columns_of(model, data):
    """Keep only the keys that are columns, the way a sync drops FPL's extra fields."""
    return {k: v for k, v in data.items() if k in model.__table__.columns}


@pytest.fixture
def team_and_position(db_session):
    db_session.add(Team(id=1, code=3, name="Arsenal", short_name="ARS"))
    db_session.add(
        ElementType(
            id=3,
            singular_name="Midfielder",
            singular_name_short="MID",
            plural_name="Midfielders",
            plural_name_short="MID",
        )
    )
    db_session.flush()


def make_event(**overrides):
    event = {
        "id": 9,
        "name": "Gameweek 9",
        "deadline_time": datetime.fromisoformat("2026-10-31T11:00:00+00:00"),
        "deadline_time_epoch": 1793444400,
        "finished": False,
        "data_checked": False,
        "is_previous": False,
        "is_current": True,
        "is_next": False,
    }
    event.update(overrides)
    return Event(**event)


def make_history(**overrides):
    row = {"element": 1, "fixture": 81, "round": 9, "total_points": 6, "value": 90}
    row.update(overrides)
    return PlayerFixtureHistory(**row)


# --- migrations ------------------------------------------------------------


def test_migrations_match_models(db_engine, test_database_url):
    # Raises if the models have changes no migration covers.
    command.check(alembic_config(test_database_url))
    assert db_engine is not None


def test_migrations_downgrade_and_upgrade(db_engine, test_database_url):
    config = alembic_config(test_database_url)
    command.downgrade(config, "base")
    assert inspect(db_engine).get_table_names() == ["alembic_version"]

    command.upgrade(config, "head")
    assert set(inspect(db_engine).get_table_names()) == {
        "alembic_version",
        *Base.metadata.tables,
    }


def test_row_level_security_on_every_table(db_engine):
    with db_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT relname, relrowsecurity FROM pg_class "
                "WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace"
            )
        ).all()
    assert dict(rows) == {
        table: True for table in ("alembic_version", *Base.metadata.tables)
    }


# --- elements --------------------------------------------------------------


@pytest.mark.usefixtures("team_and_position")
def test_element_round_trip(db_session):
    data = make_element(news_added="2026-10-20T10:30:12.123456Z")
    db_session.add(Element(**columns_of(Element, data)))
    db_session.flush()
    db_session.expire_all()

    element = db_session.get(Element, 1)
    assert element.web_name == "Saka"
    assert element.form == Decimal("6.0")
    assert element.expected_goals == Decimal("3.21")
    assert element.news_added.utcoffset().total_seconds() == 0
    assert element.chance_of_playing_next_round is None
    assert element.updated_at is not None


def test_element_requires_existing_team(db_session):
    db_session.add(Element(**columns_of(Element, make_element())))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.usefixtures("team_and_position")
@pytest.mark.parametrize("field", ["web_name", "now_cost", "status"])
def test_element_required_columns(db_session, field):
    data = columns_of(Element, make_element())
    data[field] = None
    db_session.add(Element(**data))
    with pytest.raises(IntegrityError):
        db_session.flush()


# --- events ----------------------------------------------------------------


def test_future_event_stats_can_be_null(db_session):
    db_session.add(make_event(id=20, name="Gameweek 20", is_current=False))
    db_session.flush()
    db_session.expire_all()

    event = db_session.get(Event, 20)
    assert event.most_selected is None
    assert event.top_element_points is None
    assert event.chip_plays is None


def test_event_chip_plays_round_trip(db_session):
    chip_plays = [{"chip_name": "bboost", "num_played": 814606}]
    db_session.add(
        make_event(chip_plays=chip_plays, top_element=115, top_element_points=17)
    )
    db_session.flush()
    db_session.expire_all()

    assert db_session.get(Event, 9).chip_plays == chip_plays


# --- player fixture history ------------------------------------------------


@pytest.fixture
def saka(db_session, team_and_position):  # pylint: disable=unused-argument
    db_session.add(Element(**columns_of(Element, make_element())))
    db_session.flush()


@pytest.mark.usefixtures("saka")
def test_double_gameweek_has_two_rows(db_session):
    db_session.add_all([make_history(fixture=81), make_history(fixture=85)])
    db_session.flush()

    rows = db_session.scalars(
        select(PlayerFixtureHistory).where(PlayerFixtureHistory.round == 9)
    ).all()
    assert sorted(row.fixture for row in rows) == [81, 85]


@pytest.mark.usefixtures("saka")
def test_history_is_unique_per_player_and_fixture(db_session):
    db_session.add(make_history())
    db_session.flush()
    db_session.add(make_history(total_points=8))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_history_requires_existing_player(db_session):
    db_session.add(make_history(element=999))
    with pytest.raises(IntegrityError):
        db_session.flush()


# --- sync runs -------------------------------------------------------------


def test_sync_run_defaults(db_session):
    run = SyncRun(kind="bootstrap", status="running")
    db_session.add(run)
    db_session.flush()
    db_session.refresh(run)

    assert run.id is not None
    assert run.started_at is not None
    assert run.finished_at is None
