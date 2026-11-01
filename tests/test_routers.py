# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from main import app
from src.models.element import ElementResponse
from src.util.fpl_service import FplService

pytestmark = pytest.mark.usefixtures("loaded_service")


@pytest.fixture
def client():
    # Not used as a context manager, so the startup fetch (lifespan) is skipped.
    return TestClient(app)


# --- elements -------------------------------------------------------------

def test_get_elements(client):
    response = client.get("/api/elements")
    assert response.status_code == 200
    assert [e["web_name"] for e in response.json()] == ["Saka", "Haaland", "Palmer"]


def test_get_elements_uses_response_model(client):
    element = client.get("/api/elements").json()[0]
    assert element.keys() == ElementResponse.model_fields.keys()
    assert "influence_rank" not in element


def test_element_decimal_strings_become_numbers(client):
    element = client.get("/api/elements/1").json()
    assert element["form"] == 6.0
    assert element["selected_by_percent"] == 40.1
    assert element["expected_goals"] == 3.21


def test_element_nullable_fields(client, loaded_service):
    loaded_service.fpl_data["elements"][0].update(
        chance_of_playing_next_round=75,
        news_added="2026-10-20T10:30:12.123456Z",
        ep_next=None,
    )
    element = client.get("/api/elements/1").json()
    assert element["chance_of_playing_next_round"] == 75
    assert element["chance_of_playing_this_round"] is None
    assert element["news_added"] == "2026-10-20T10:30:12.123456Z"
    assert element["ep_next"] is None


def test_get_elements_empty(client, loaded_service):
    loaded_service.fpl_data["elements"] = []
    response = client.get("/api/elements")
    assert response.status_code == 200
    assert response.json() == []


def test_get_element_by_id(client):
    response = client.get("/api/elements/1")
    assert response.status_code == 200
    assert response.json()["web_name"] == "Saka"


def test_get_element_by_id_not_found(client):
    response = client.get("/api/elements/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Element not found"}


def test_get_element_by_id_invalid(client):
    assert client.get("/api/elements/abc").status_code == 422


def test_get_elements_by_type(client):
    response = client.get("/api/elements/position/3")
    assert response.status_code == 200
    assert [e["web_name"] for e in response.json()] == ["Saka", "Palmer"]


def test_get_elements_by_type_not_found(client):
    response = client.get("/api/elements/position/1")
    assert response.status_code == 404
    assert response.json() == {"detail": "Elements not found"}


# --- events ---------------------------------------------------------------

def test_get_events(client, fpl_data):
    response = client.get("/api/events")
    assert response.status_code == 200
    assert response.json() == fpl_data["events"]


def test_get_events_empty(client, loaded_service):
    loaded_service.fpl_data["events"] = []
    response = client.get("/api/events")
    assert response.status_code == 200
    assert response.json() == []


def test_get_event_by_id(client):
    response = client.get("/api/events/1")
    assert response.status_code == 200
    assert response.json()["name"] == "Gameweek 1"


def test_get_event_by_id_not_found(client):
    response = client.get("/api/events/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def test_get_current_event(client, monkeypatch):
    monkeypatch.setattr(FplService, "get_fpl_api_data", AsyncMock())
    response = client.get("/api/events/current-event/")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 2
    assert body["top_element_info"] == {"id": 1, "points": 20}
    assert "is_current" not in body  # filtered by EventResponse


def test_get_current_event_not_found(client, monkeypatch, loaded_service):
    monkeypatch.setattr(FplService, "get_fpl_api_data", AsyncMock())
    for event in loaded_service.fpl_data["events"]:
        event["is_current"] = False
    response = client.get("/api/events/current-event/")
    assert response.status_code == 404
    assert response.json() == {"detail": "Current event not found"}


# --- teams ----------------------------------------------------------------

def test_get_teams(client, fpl_data):
    response = client.get("/api/teams")
    assert response.status_code == 200
    assert response.json() == fpl_data["teams"]


def test_get_teams_empty(client, loaded_service):
    loaded_service.fpl_data["teams"] = []
    response = client.get("/api/teams")
    assert response.status_code == 200
    assert response.json() == []


def test_get_team_by_name(client):
    response = client.get("/api/teams/Man City")
    assert response.status_code == 200
    assert response.json() == {"id": 2, "name": "Man City"}


def test_get_team_by_name_not_found(client):
    response = client.get("/api/teams/Nowhere")
    assert response.status_code == 404
    assert response.json() == {"detail": "Team not found"}


# --- data not loaded ------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        "/api/elements",
        "/api/elements/1",
        "/api/elements/position/3",
        "/api/events",
        "/api/events/1",
        "/api/teams",
        "/api/teams/Arsenal",
    ],
)
def test_returns_503_when_data_not_loaded(client, loaded_service, path):
    loaded_service.fpl_data = None
    response = client.get(path)
    assert response.status_code == 503
    assert response.json() == {"detail": "FPL data is currently unavailable"}


def test_current_event_returns_503_when_refresh_fails_and_no_cache(
    client, monkeypatch, loaded_service
):
    loaded_service.fpl_data = None
    monkeypatch.setattr(FplService, "get_fpl_api_data", AsyncMock())
    assert client.get("/api/events/current-event/").status_code == 503
