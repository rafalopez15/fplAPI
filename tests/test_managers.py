# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""The manager endpoints and services, which call FPL live (mocked here)."""
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from main import app
from src.models.manager import HistoryResponse, ManagerResponse, TransferResponse
from src.routers import managers as managers_router
from src.services import managers
from src.util import fpl_client
from src.util.fpl_client import FplNotFoundError, FplUnavailableError
from tests.conftest import make_fpl_history, make_fpl_manager, make_fpl_transfers

FETCHES = {
    "/api/managers/1": "fetch_manager",
    "/api/managers/1/transfers": "fetch_manager_transfers",
    "/api/managers/1/history": "fetch_manager_history",
}


@pytest.fixture
def api():
    # These endpoints don't touch the database, so no seeded session is needed.
    return TestClient(app)


@pytest.fixture
def fpl(monkeypatch):
    """Mock the three FPL fetches with realistic payloads. Returns the mocks by name."""
    mocks = {
        "fetch_manager": Mock(return_value=make_fpl_manager()),
        "fetch_manager_transfers": Mock(return_value=make_fpl_transfers()),
        "fetch_manager_history": Mock(return_value=make_fpl_history()),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(fpl_client, name, mock)
    return mocks


# --- services ---------------------------------------------------------------

@pytest.mark.usefixtures("fpl")
def test_get_manager_service():
    result = managers.get_manager(1)
    assert isinstance(result, ManagerResponse)
    assert (result.name, result.player_first_name) == ("Solio Moose", "Chris")


@pytest.mark.usefixtures("fpl")
def test_get_transfers_service_keeps_fpl_order():
    result = managers.get_transfers(1)
    assert all(isinstance(t, TransferResponse) for t in result)
    assert [t.event for t in result] == [9, 4]


@pytest.mark.usefixtures("fpl")
def test_get_history_service():
    result = managers.get_history(1)
    assert isinstance(result, HistoryResponse)
    assert [g.total_points for g in result.current] == [72, 123]


def test_services_pass_the_manager_id(fpl):
    managers.get_manager(42)
    managers.get_transfers(42)
    managers.get_history(42)
    for mock in fpl.values():
        mock.assert_called_once_with(42)


# --- GET /api/managers/{id} --------------------------------------------------

@pytest.mark.usefixtures("fpl")
def test_get_manager(api):
    response = api.get("/api/managers/1")
    assert response.status_code == 200
    body = response.json()
    assert body.keys() == ManagerResponse.model_fields.keys()
    assert body["name"] == "Solio Moose"
    assert body["last_deadline_value"] == 1022
    assert "leagues" not in body


def test_manager_optional_fields_can_be_missing(api, fpl):
    fpl["fetch_manager"].return_value = {
        "id": 7, "name": "New Team", "player_first_name": "A", "player_last_name": "B",
    }
    body = api.get("/api/managers/7").json()
    assert body["summary_overall_rank"] is None


# --- GET /api/managers/{id}/transfers ----------------------------------------

@pytest.mark.usefixtures("fpl")
def test_get_transfers(api):
    response = api.get("/api/managers/1/transfers")
    assert response.status_code == 200
    body = response.json()
    assert [t["element_in"] for t in body] == [566, 2]  # newest first
    assert body[0] == {
        "element_in": 566, "element_out": 114, "event": 9,
        "time": "2026-10-31T10:08:30.794468Z",
        "element_in_cost": 50, "element_out_cost": 45,
    }


def test_get_transfers_empty(api, fpl):
    fpl["fetch_manager_transfers"].return_value = []
    response = api.get("/api/managers/1/transfers")
    assert response.status_code == 200
    assert response.json() == []


# --- GET /api/managers/{id}/history ------------------------------------------

@pytest.mark.usefixtures("fpl")
def test_get_history(api):
    response = api.get("/api/managers/1/history")
    assert response.status_code == 200
    body = response.json()
    assert body.keys() == {"current", "chips", "past"}
    assert body["current"][1]["total_points"] == 123
    assert "percentile_rank" not in body["current"][0]
    assert body["chips"] == [
        {"name": "bboost", "event": 2, "time": "2026-08-28T17:25:01.123184Z"}
    ]
    assert body["past"] == [{"season_name": "2024/25", "total_points": 2301, "rank": 150234}]


# --- caching -----------------------------------------------------------------

@pytest.mark.usefixtures("fpl")
@pytest.mark.parametrize(
    "path, cache",
    [
        ("/api/managers/1", managers_router.MANAGER_CACHE),
        ("/api/managers/1/transfers", managers_router.TRANSFERS_CACHE),
        ("/api/managers/1/history", managers_router.HISTORY_CACHE),
    ],
)
def test_successful_responses_are_cacheable(api, path, cache):
    response = api.get(path)
    assert response.headers["cache-control"] == cache
    assert "s-maxage=" in cache


# --- errors --------------------------------------------------------------------

@pytest.mark.parametrize("path, fetch", FETCHES.items())
def test_unknown_manager_returns_404(api, fpl, path, fetch):
    fpl[fetch].side_effect = FplNotFoundError("nope")
    response = api.get(path)
    assert response.status_code == 404
    assert response.json() == {"detail": "Manager not found"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path, fetch", FETCHES.items())
def test_fpl_unavailable_returns_503(api, fpl, path, fetch):
    fpl[fetch].side_effect = FplUnavailableError("timed out")
    response = api.get(path)
    assert response.status_code == 503
    assert response.json() == {"detail": "FPL is unavailable right now"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("bad_id", ["0", "-5", "abc", "1.5"])
@pytest.mark.parametrize("suffix", ["", "/transfers", "/history"])
def test_invalid_id_returns_422_without_calling_fpl(api, fpl, bad_id, suffix):
    response = api.get(f"/api/managers/{bad_id}{suffix}")
    assert response.status_code == 422
    for mock in fpl.values():
        mock.assert_not_called()
