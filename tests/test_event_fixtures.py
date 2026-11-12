# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""GET /api/events/{id}/fixtures and its service, which call FPL live (mocked here)."""

from unittest.mock import Mock

import pytest
from src.models.fixture import LiveFixtureResponse
from src.routers import events as events_router
from src.services import events
from src.util import fpl_client
from src.util.fpl_client import FplNotFoundError, FplUnavailableError
from tests.conftest import make_fixture


def make_fpl_event_fixtures():
    """Gameweek 10's matches as FPL sends them: one played, one in play, one to come."""
    return [
        make_fixture(
            id=91,
            kickoff_time="2026-11-07T15:00:00Z",
            started=True,
            finished_provisional=True,
            minutes=90,
            team_h_score=2,
            team_a_score=1,
            stats=[{"identifier": "goals_scored", "h": [], "a": []}],
        ),
        make_fixture(
            id=92,
            kickoff_time="2026-11-07T17:30:00Z",
            started=True,
            minutes=63,
            team_h_score=0,
            team_a_score=0,
        ),
        make_fixture(id=93, kickoff_time="2026-11-08T16:30:00Z"),
    ]


@pytest.fixture
def api(client):
    # The route saves FPL's answer, and serves it while FPL is down.
    return client


@pytest.fixture
def fetch(monkeypatch):
    mock = Mock(return_value=make_fpl_event_fixtures())
    monkeypatch.setattr(fpl_client, "fetch_event_fixtures", mock)
    return mock


# --- service -----------------------------------------------------------------


def test_get_fixtures_service(fetch):
    result = events.get_fixtures(10)
    fetch.assert_called_once_with(10)
    assert all(isinstance(item, LiveFixtureResponse) for item in result)
    assert [(f.id, f.minutes, f.finished_provisional) for f in result] == [
        (91, 90, True),
        (92, 63, False),
        (93, 0, False),
    ]


def test_get_fixtures_service_orders_by_kickoff(fetch):
    fetch.return_value = [
        make_fixture(id=95, kickoff_time=None),
        make_fixture(id=94, kickoff_time="2026-11-08T14:00:00Z"),
        make_fixture(id=93, kickoff_time="2026-11-07T15:00:00Z"),
        make_fixture(id=92, kickoff_time="2026-11-07T15:00:00Z"),
    ]
    assert [f.id for f in events.get_fixtures(10)] == [92, 93, 94, 95]


def test_get_fixtures_service_handles_missing_live_fields(fetch):
    row = make_fixture()
    del row["minutes"], row["finished_provisional"]
    fetch.return_value = [row]
    fixture = events.get_fixtures(10)[0]
    assert (fixture.minutes, fixture.finished_provisional) == (0, False)


def test_get_fixtures_service_raises_not_found_for_an_empty_list(fetch):
    # FPL's answer for a gameweek it doesn't have.
    fetch.return_value = []
    with pytest.raises(FplNotFoundError):
        events.get_fixtures(39)


# --- route -------------------------------------------------------------------


@pytest.mark.usefixtures("fetch")
def test_get_fixtures(api):
    response = api.get("/api/events/10/fixtures")
    assert response.status_code == 200
    body = response.json()
    played = body[0]
    # No stats, code, pulse_id or provisional_start_time.
    assert played.keys() == LiveFixtureResponse.model_fields.keys()
    assert (played["team_h_score"], played["team_a_score"]) == (2, 1)
    assert (played["minutes"], played["finished_provisional"]) == (90, True)
    assert (played["started"], played["finished"]) == (True, False)
    assert [fixture["id"] for fixture in body] == [91, 92, 93]
    assert response.headers["cache-control"] == events_router.LIVE_CACHE


def test_an_unreadable_fixture_is_skipped(api, fetch, caplog):
    fetch.return_value = [make_fixture(id=91, team_h=None), make_fixture(id=92)]
    response = api.get("/api/events/10/fixtures")
    assert response.status_code == 200
    assert [fixture["id"] for fixture in response.json()] == [92]
    assert "Skipping unreadable fixture 91" in caplog.text


@pytest.mark.parametrize("error", [None, FplNotFoundError("nope")])
def test_get_fixtures_unknown_gameweek_returns_404(api, fetch, error):
    # FPL answers [] for a gameweek it doesn't have; a 404 is handled the same.
    fetch.return_value = []
    fetch.side_effect = error
    response = api.get("/api/events/39/fixtures")
    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}
    assert response.headers["cache-control"] == "no-store"


def test_get_fixtures_fpl_unavailable_returns_503(api, fetch):
    fetch.side_effect = FplUnavailableError("timed out")
    response = api.get("/api/events/10/fixtures")
    assert response.status_code == 503
    assert response.json() == {"detail": "FPL is unavailable right now"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("bad_id", ["0", "-1", "abc", "2147483648"])
def test_get_fixtures_invalid_id_returns_422_without_calling_fpl(api, fetch, bad_id):
    assert api.get(f"/api/events/{bad_id}/fixtures").status_code == 422
    fetch.assert_not_called()
