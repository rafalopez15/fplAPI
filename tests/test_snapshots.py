# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""The last good copy of each live FPL route, served while FPL is down."""

import json
import logging
from datetime import datetime
from typing import List
from unittest.mock import Mock

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from src.db.models import FplSnapshot
from src.models.event import LiveElementResponse
from src.models.manager import HistoryResponse
from src.routers.live import STALE_CACHE
from src.services import snapshots, transfer_points
from src.util import fpl_client
from src.util.fpl_client import FplNotFoundError, FplUnavailableError
from tests.conftest import (
    make_fixture,
    make_fpl_event_live,
    make_fpl_history,
    make_fpl_league_standings,
    make_fpl_manager,
    make_fpl_new_entry,
    make_fpl_picks,
    make_fpl_transfers,
)

# Each live route, the fetch that answers it, and its snapshot key.
ROUTES = [
    ("/api/managers/1", "fetch_manager", "managers/1"),
    ("/api/managers/1/transfers", "fetch_manager_transfers", "managers/1/transfers"),
    ("/api/managers/1/history", "fetch_manager_history", "managers/1/history"),
    ("/api/managers/1/picks?event=9", "fetch_manager_picks", "managers/1/picks/9"),
    ("/api/managers/1/picks", "fetch_manager", "managers/1/picks/current"),
    ("/api/events/9/live", "fetch_event_live", "events/9/live"),
    ("/api/events/10/fixtures", "fetch_event_fixtures", "events/10/fixtures"),
    ("/api/leagues/5508", "fetch_league_standings", "leagues/5508/1"),
]


PAYLOADS = {
    "fetch_manager": make_fpl_manager,
    "fetch_manager_transfers": make_fpl_transfers,
    "fetch_manager_history": make_fpl_history,
    "fetch_manager_picks": make_fpl_picks,
    "fetch_event_live": make_fpl_event_live,
    # In play, so the stale copy must keep the live fields.
    "fetch_event_fixtures": lambda: [make_fixture(started=True, minutes=63)],
    "fetch_league_standings": lambda: make_fpl_league_standings(
        new_entries=[make_fpl_new_entry(8533420, "Kt")]
    ),
}


@pytest.fixture
def fpl(monkeypatch):
    """Mock every live FPL fetch. Returns the mocks by name."""
    mocks = {name: Mock(return_value=build()) for name, build in PAYLOADS.items()}
    for name, mock in mocks.items():
        monkeypatch.setattr(fpl_client, name, mock)
    return mocks


def saved_keys(session):
    return set(session.scalars(select(FplSnapshot.key)))


# --- service -----------------------------------------------------------------


def test_save_and_load(db_session):
    history = HistoryResponse.model_validate(make_fpl_history())
    snapshots.save(db_session, "managers/1/history", history, HistoryResponse)
    result, fetched_at = snapshots.load(
        db_session, "managers/1/history", HistoryResponse
    )
    assert result == history
    assert isinstance(fetched_at, datetime) and fetched_at.tzinfo is not None


def test_save_and_load_a_list(db_session):
    live = [LiveElementResponse(id=1, total_points=5, minutes=90)]
    kind = List[LiveElementResponse]
    snapshots.save(db_session, "events/9/live", live, kind)
    assert snapshots.load(db_session, "events/9/live", kind)[0] == live


def test_save_replaces_the_last_snapshot(db_session):
    kind = List[LiveElementResponse]
    snapshots.save(db_session, "events/9/live", [LiveElementResponse(id=1)], kind)
    snapshots.save(db_session, "events/9/live", [LiveElementResponse(id=2)], kind)
    assert snapshots.load(db_session, "events/9/live", kind)[0] == [
        LiveElementResponse(id=2)
    ]
    assert saved_keys(db_session) == {"events/9/live"}


def test_load_without_a_snapshot(db_session):
    assert snapshots.load(db_session, "managers/1", HistoryResponse) is None


def test_a_snapshot_that_no_longer_fits_its_model_is_not_served(db_session, caplog):
    # e.g. the model gained a required field since the snapshot was saved.
    db_session.add(
        FplSnapshot(key="managers/1/history", body={"x": 1}, fetched_at=datetime.now())
    )
    with caplog.at_level(logging.WARNING):
        assert snapshots.load(db_session, "managers/1/history", HistoryResponse) is None
    assert "no longer fits" in caplog.text


def test_a_failed_save_is_logged_not_raised(caplog):
    session = Mock()
    session.execute.side_effect = OperationalError("insert", {}, Exception("down"))
    with caplog.at_level(logging.WARNING):
        snapshots.save(session, "events/9/live", [], List[LiveElementResponse])
    session.rollback.assert_called_once()
    assert "Couldn't save snapshot events/9/live" in caplog.text


def test_a_failed_load_is_logged_and_returns_none(caplog):
    session = Mock()
    session.get.side_effect = OperationalError("select", {}, Exception("down"))
    with caplog.at_level(logging.WARNING):
        assert snapshots.load(session, "managers/1", HistoryResponse) is None
    assert "Couldn't load snapshot managers/1" in caplog.text


# --- routes ------------------------------------------------------------------


@pytest.mark.usefixtures("fpl")
@pytest.mark.parametrize("path, _fetch, key", ROUTES)
def test_a_live_answer_is_saved(client, seeded_session, path, _fetch, key):
    assert client.get(path).status_code == 200
    assert key in saved_keys(seeded_session)


@pytest.mark.parametrize("path, fetch, _key", ROUTES)
def test_the_saved_copy_is_served_while_fpl_is_down(client, fpl, path, fetch, _key):
    fresh = client.get(path)
    fpl[fetch].side_effect = FplUnavailableError("updating")
    stale = client.get(path)
    assert stale.status_code == 200
    assert stale.json() == fresh.json()
    assert stale.headers["cache-control"] == STALE_CACHE
    fetched_at = datetime.fromisoformat(stale.headers["x-data-stale-as-of"])
    assert fetched_at.tzinfo is not None


@pytest.mark.parametrize("path, fetch, _key", ROUTES)
def test_fpl_down_with_no_saved_copy_returns_503(client, fpl, path, fetch, _key):
    fpl[fetch].side_effect = FplUnavailableError("updating")
    response = client.get(path)
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert "x-data-stale-as-of" not in response.headers


@pytest.mark.parametrize("path, fetch, _key", ROUTES)
def test_a_404_is_never_served_from_a_snapshot(client, fpl, path, fetch, _key):
    client.get(path)
    fpl[fetch].side_effect = FplNotFoundError("gone")
    response = client.get(path)
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.usefixtures("fpl")
def test_a_fresh_answer_is_not_marked_stale(client):
    response = client.get("/api/managers/1")
    assert "x-data-stale-as-of" not in response.headers


def test_transfers_fall_back_whole_when_only_history_fails(client, fpl):
    # /transfers calls FPL twice; either failing serves the whole saved copy.
    fresh = client.get("/api/managers/1/transfers")
    fpl["fetch_manager_history"].side_effect = FplUnavailableError("updating")
    stale = client.get("/api/managers/1/transfers")
    assert stale.status_code == 200
    assert stale.json() == fresh.json()
    assert "x-data-stale-as-of" in stale.headers


def test_transfers_are_saved_when_the_points_cant_be_read(client, fpl, monkeypatch):
    # A failed query leaves the shared session's transaction aborted; the save
    # must still go through, with null points.
    def failing(session, _players):
        session.execute(text("SELECT 1 / 0"))

    monkeypatch.setattr(transfer_points, "load_points", failing)
    assert client.get("/api/managers/1/transfers").status_code == 200
    fpl["fetch_manager_transfers"].side_effect = FplUnavailableError("updating")
    stale = client.get("/api/managers/1/transfers")
    assert stale.status_code == 200
    assert all(row["net_points"] is None for row in stale.json())


def test_only_a_leagues_first_page_is_saved(client, seeded_session, fpl):
    fpl["fetch_league_standings"].return_value = make_fpl_league_standings(page=2)
    assert client.get("/api/leagues/5508?page=2").status_code == 200
    assert not saved_keys(seeded_session)
    fpl["fetch_league_standings"].side_effect = FplUnavailableError("updating")
    assert client.get("/api/leagues/5508?page=2").status_code == 503


def test_an_empty_league_page_is_not_saved(client, seeded_session, fpl):
    fpl["fetch_league_standings"].return_value = make_fpl_league_standings(results=[])
    assert client.get("/api/leagues/5508").status_code == 200
    assert not saved_keys(seeded_session)


def test_a_new_league_with_only_new_entries_is_saved(client, seeded_session, fpl):
    # Teams that just joined aren't in the standings until the next update.
    fpl["fetch_league_standings"].return_value = make_fpl_league_standings(
        results=[], new_entries=[make_fpl_new_entry(8533420, "Kt")]
    )
    client.get("/api/leagues/5508")
    assert saved_keys(seeded_session) == {"leagues/5508/1"}


def test_live_points_before_a_gameweek_starts_are_not_saved(
    client, seeded_session, fpl
):
    fpl["fetch_event_live"].return_value = {"elements": []}
    assert client.get("/api/events/11/live").json() == []
    assert not saved_keys(seeded_session)


@pytest.mark.parametrize(
    "rows",
    [[make_fixture(team_h=None)], []],
    ids=["no readable match", "every match postponed"],
)
def test_fixtures_with_no_match_are_not_saved(client, seeded_session, fpl, rows):
    fpl["fetch_event_fixtures"].return_value = rows
    assert client.get("/api/events/10/fixtures").json() == []
    assert not saved_keys(seeded_session)


def test_picks_before_the_first_deadline_are_not_saved(client, seeded_session, fpl):
    fpl["fetch_manager"].return_value = make_fpl_manager(current_event=None)
    assert client.get("/api/managers/1/picks").status_code == 404
    assert "managers/1/picks/current" not in saved_keys(seeded_session)


@pytest.mark.usefixtures("fpl")
def test_real_names_are_never_saved(client, seeded_session):
    # FPL sends the manager's name (Chris Musson) on the manager, and on league
    # standings and new entries. None of it may reach a snapshot.
    for path, _fetch, _key in ROUTES:
        client.get(path)
    bodies = json.dumps(list(seeded_session.scalars(select(FplSnapshot.body))))
    assert "Chris" not in bodies and "Musson" not in bodies
    for field in ("player_name", "player_first_name", "player_last_name"):
        assert field not in bodies
