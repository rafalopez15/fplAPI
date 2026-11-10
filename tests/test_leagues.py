# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""GET /api/leagues/{id} and its service, which call FPL live (mocked here)."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from main import app
from src.models.league import LeagueStandingsResponse
from src.routers import leagues as leagues_router
from src.services import leagues
from src.util import fpl_client
from src.util.fpl_client import FplNotFoundError, FplUnavailableError
from tests.conftest import make_fpl_league_standings, make_fpl_standing


@pytest.fixture
def api():
    # The endpoint doesn't touch the database, so no seeded session is needed.
    return TestClient(app)


@pytest.fixture
def fetch(monkeypatch):
    mock = Mock(return_value=make_fpl_league_standings())
    monkeypatch.setattr(fpl_client, "fetch_league_standings", mock)
    return mock


# --- service -----------------------------------------------------------------


def test_get_standings_service(fetch):
    result = leagues.get_standings(5508, 2)
    assert isinstance(result, LeagueStandingsResponse)
    assert (result.id, result.name) == (5508, "FPLDev")
    fetch.assert_called_once_with(5508, 2)


def test_get_standings_service_handles_missing_standings(fetch):
    fetch.return_value = {"league": {"id": 5508, "name": "FPLDev"}}
    result = leagues.get_standings(5508, 3)
    assert (result.page, result.has_next, result.standings) == (3, False, [])
    assert result.last_updated is None


# --- GET /api/leagues/{id} -------------------------------------------------------


def test_get_league(api, fetch):
    response = api.get("/api/leagues/5508")
    assert response.status_code == 200
    assert response.json() == {
        "id": 5508,
        "name": "FPLDev",
        "last_updated": "2026-11-10T16:04:56Z",
        "page": 1,
        "has_next": False,
        "standings": [
            {
                "entry": 7700093,
                "entry_name": "Amos's Team",
                "rank": 1,
                "last_rank": 2,
                "total": 699,
                "event_total": 40,
            },
            {
                "entry": 1,
                "entry_name": "Solio Moose",
                "rank": 2,
                "last_rank": 3,
                "total": 698,
                "event_total": 40,
            },
        ],
    }
    fetch.assert_called_once_with(5508, 1)


def test_get_league_page(api, fetch):
    fetch.return_value = make_fpl_league_standings(page=2, has_next=True)
    body = api.get("/api/leagues/5508?page=2").json()
    assert (body["page"], body["has_next"]) == (2, True)
    fetch.assert_called_once_with(5508, 2)


def test_get_league_past_the_end_is_an_empty_page(api, fetch):
    fetch.return_value = make_fpl_league_standings(page=9, results=[])
    response = api.get("/api/leagues/5508?page=9")
    assert response.status_code == 200
    body = response.json()
    assert (body["page"], body["has_next"], body["standings"]) == (9, False, [])


def test_missing_standing_fields_are_null(api, fetch):
    row = make_fpl_standing(1, "Solio Moose", 1)
    for key in ("rank", "last_rank", "total", "event_total"):
        del row[key]
    fetch.return_value = make_fpl_league_standings(results=[row])
    standing = api.get("/api/leagues/5508").json()["standings"][0]
    assert standing == {
        "entry": 1,
        "entry_name": "Solio Moose",
        "rank": None,
        "last_rank": None,
        "total": None,
        "event_total": None,
    }


@pytest.mark.usefixtures("fetch")
def test_real_names_never_leave_the_api(api):
    # FPL sends each manager's name as player_name (make_fpl_standing).
    text = api.get("/api/leagues/5508").text
    assert "Chris" not in text and "Musson" not in text
    assert "player_name" not in text


@pytest.mark.usefixtures("fetch")
def test_successful_response_is_cacheable(api):
    response = api.get("/api/leagues/5508")
    assert response.headers["cache-control"] == leagues_router.LEAGUE_CACHE


# --- errors --------------------------------------------------------------------


def test_unknown_league_returns_404(api, fetch):
    fetch.side_effect = FplNotFoundError("nope")
    response = api.get("/api/leagues/5508")
    assert response.status_code == 404
    assert response.json() == {"detail": "League not found"}
    assert response.headers["cache-control"] == "no-store"


def test_fpl_unavailable_returns_503(api, fetch):
    fetch.side_effect = FplUnavailableError("timed out")
    response = api.get("/api/leagues/5508")
    assert response.status_code == 503
    assert response.json() == {"detail": "FPL is unavailable right now"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("bad_id", ["0", "-5", "abc", "1.5", "2147483648"])
def test_invalid_id_returns_422_without_calling_fpl(api, fetch, bad_id):
    assert api.get(f"/api/leagues/{bad_id}").status_code == 422
    fetch.assert_not_called()


@pytest.mark.parametrize("bad_page", ["0", "-1", "abc"])
def test_invalid_page_returns_422_without_calling_fpl(api, fetch, bad_page):
    assert api.get(f"/api/leagues/5508?page={bad_page}").status_code == 422
    fetch.assert_not_called()
