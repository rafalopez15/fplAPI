# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""The manager endpoints and services, which call FPL live (mocked here)."""

from unittest.mock import Mock

import pytest
from src.models.manager import (
    HistoryResponse,
    ManagerResponse,
    PicksResponse,
    TransferResponse,
)
from src.routers import managers as managers_router
from src.services import managers
from src.util import fpl_client
from src.util.fpl_client import FplNotFoundError, FplUnavailableError
from tests.conftest import (
    make_fpl_history,
    make_fpl_manager,
    make_fpl_picks,
    make_fpl_transfers,
)

FETCHES = {
    "/api/managers/1": "fetch_manager",
    "/api/managers/1/transfers": "fetch_manager_transfers",
    "/api/managers/1/history": "fetch_manager_history",
    "/api/managers/1/picks?event=9": "fetch_manager_picks",
}


@pytest.fixture
def api(client):
    # Only /transfers reads the database (stored gameweek points); the seeded
    # test database has none, so its points are null here. See test_transfer_points.
    return client


@pytest.fixture
def fpl(monkeypatch):
    """Mock the FPL fetches with realistic payloads. Returns the mocks by name."""
    mocks = {
        "fetch_manager": Mock(return_value=make_fpl_manager()),
        "fetch_manager_transfers": Mock(return_value=make_fpl_transfers()),
        "fetch_manager_history": Mock(return_value=make_fpl_history()),
        "fetch_manager_picks": Mock(return_value=make_fpl_picks()),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(fpl_client, name, mock)
    return mocks


# --- services ---------------------------------------------------------------


@pytest.mark.usefixtures("fpl")
def test_get_manager_service():
    result = managers.get_manager(1)
    assert isinstance(result, ManagerResponse)
    assert result.name == "Solio Moose"


@pytest.mark.usefixtures("fpl")
def test_get_transfers_service_keeps_fpl_order(seeded_session):
    result = managers.get_transfers(1, seeded_session)
    assert all(isinstance(t, TransferResponse) for t in result)
    assert [t.event for t in result] == [9, 4]


@pytest.mark.usefixtures("fpl")
def test_get_history_service():
    result = managers.get_history(1)
    assert isinstance(result, HistoryResponse)
    assert [g.total_points for g in result.current] == [72, 123]


@pytest.mark.usefixtures("fpl")
def test_get_picks_service():
    result = managers.get_picks(1, 9)
    assert isinstance(result, PicksResponse)
    assert len(result.picks) == 15


def test_get_picks_service_defaults_to_the_current_event(fpl):
    fpl["fetch_manager"].return_value = make_fpl_manager(current_event=7)
    managers.get_picks(42)
    fpl["fetch_manager"].assert_called_once_with(42)
    fpl["fetch_manager_picks"].assert_called_once_with(42, 7)


def test_get_picks_service_skips_the_manager_call_for_an_explicit_event(fpl):
    managers.get_picks(42, 3)
    fpl["fetch_manager"].assert_not_called()
    fpl["fetch_manager_picks"].assert_called_once_with(42, 3)


def test_get_picks_service_returns_none_before_the_first_deadline(fpl):
    fpl["fetch_manager"].return_value = make_fpl_manager(current_event=None)
    assert managers.get_picks(42) is None
    fpl["fetch_manager_picks"].assert_not_called()


def test_services_pass_the_manager_id(fpl, seeded_session):
    managers.get_manager(42)
    managers.get_transfers(42, seeded_session)  # also fetches history, for Free Hits
    managers.get_history(42)
    fpl["fetch_manager"].assert_called_once_with(42)
    fpl["fetch_manager_transfers"].assert_called_once_with(42)
    assert fpl["fetch_manager_history"].call_args_list == [((42,),), ((42,),)]


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


@pytest.mark.usefixtures("fpl")
@pytest.mark.parametrize("path", FETCHES)
def test_real_names_never_leave_the_api(api, path):
    # FPL sends the manager's name (make_fpl_manager: Chris Musson). No manager
    # route may pass it on, under any key.
    text = api.get(path).text
    assert "Chris" not in text and "Musson" not in text
    assert "player_first_name" not in text and "player_last_name" not in text


def test_manager_optional_fields_can_be_missing(api, fpl):
    fpl["fetch_manager"].return_value = {
        "id": 7,
        "name": "New Team",
        "player_first_name": "A",
        "player_last_name": "B",
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
        "element_in": 566,
        "element_out": 114,
        "event": 9,
        "time": "2026-10-31T10:08:30.794468Z",
        "element_in_cost": 50,
        "element_out_cost": 45,
        "is_churn": False,
        "points_in": None,
        "points_out": None,
        "net_points": None,
    }


def test_get_transfers_empty(api, fpl):
    fpl["fetch_manager_transfers"].return_value = []
    response = api.get("/api/managers/1/transfers")
    assert response.status_code == 200
    assert response.json() == []
    fpl["fetch_manager_history"].assert_not_called()  # no transfers, no need for chips


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
    assert body["past"] == [
        {"season_name": "2024/25", "total_points": 2301, "rank": 150234}
    ]


# --- GET /api/managers/{id}/picks --------------------------------------------


@pytest.mark.usefixtures("fpl")
def test_get_picks(api):
    response = api.get("/api/managers/1/picks?event=9")
    assert response.status_code == 200
    body = response.json()
    assert body.keys() == PicksResponse.model_fields.keys()
    assert body["active_chip"] is None
    assert [p["position"] for p in body["picks"]] == list(range(1, 16))
    assert body["picks"][4] == {
        "element": 105,
        "position": 5,
        "multiplier": 2,
        "is_captain": True,
        "is_vice_captain": False,
        "element_type": 2,
    }
    assert [p["multiplier"] for p in body["picks"][11:]] == [0, 0, 0, 0]  # bench
    assert body["automatic_subs"] == [
        {"element_in": 113, "element_out": 103, "event": 9}
    ]
    assert body["entry_history"]["event"] == 9
    assert body["entry_history"]["points_on_bench"] == 13
    assert "percentile_rank" not in body["entry_history"]


def test_get_picks_defaults_to_the_current_event(api, fpl):
    response = api.get("/api/managers/1/picks")
    assert response.status_code == 200
    fpl["fetch_manager_picks"].assert_called_once_with(
        1, 9
    )  # make_fpl_manager's current_event


def test_get_picks_with_a_chip(api, fpl):
    fpl["fetch_manager_picks"].return_value = make_fpl_picks(active_chip="3xc")
    body = api.get("/api/managers/1/picks?event=9").json()
    assert body["active_chip"] == "3xc"
    assert body["picks"][4]["multiplier"] == 3


def test_get_picks_before_the_first_deadline_returns_404(api, fpl):
    fpl["fetch_manager"].return_value = make_fpl_manager(current_event=None)
    response = api.get("/api/managers/1/picks")
    assert response.status_code == 404
    assert response.json() == {"detail": "Manager not found"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("bad_event", ["0", "-1", "abc"])
def test_get_picks_invalid_event_returns_422_without_calling_fpl(api, fpl, bad_event):
    response = api.get(f"/api/managers/1/picks?event={bad_event}")
    assert response.status_code == 422
    for mock in fpl.values():
        mock.assert_not_called()


# --- caching -----------------------------------------------------------------


@pytest.mark.usefixtures("fpl")
@pytest.mark.parametrize(
    "path, cache",
    [
        ("/api/managers/1", managers_router.MANAGER_CACHE),
        ("/api/managers/1/transfers", managers_router.TRANSFERS_CACHE),
        ("/api/managers/1/history", managers_router.HISTORY_CACHE),
        ("/api/managers/1/picks", managers_router.PICKS_CACHE),
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


@pytest.mark.parametrize("bad_id", ["0", "-5", "abc", "1.5", "2147483648"])
@pytest.mark.parametrize("suffix", ["", "/transfers", "/history", "/picks"])
def test_invalid_id_returns_422_without_calling_fpl(api, fpl, bad_id, suffix):
    response = api.get(f"/api/managers/{bad_id}{suffix}")
    assert response.status_code == 422
    for mock in fpl.values():
        mock.assert_not_called()
