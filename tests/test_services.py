import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
import requests
from src.models.element import ElementResponse
from src.models.event import EventResponse
from src.services import elements, events, teams
from src.util.fpl_service import FplDataUnavailableError, FplService

pytestmark = pytest.mark.usefixtures("loaded_service")


# --- elements -------------------------------------------------------------

def test_get_elements(fpl_data):
    assert elements.get_elements() == fpl_data["elements"]


def test_get_element_by_id_found():
    result = elements.get_element_by_id(2)
    assert isinstance(result, ElementResponse)
    assert result.web_name == "Haaland"


def test_get_element_by_id_not_found():
    assert elements.get_element_by_id(999) is None


def test_get_elements_by_type():
    result = elements.get_elements_by_type(3)
    assert all(isinstance(e, ElementResponse) for e in result)
    assert [e.web_name for e in result] == ["Saka", "Palmer"]


def test_get_elements_by_type_no_match():
    assert not elements.get_elements_by_type(1)


def test_get_element_types(fpl_data):
    assert elements.get_element_types() == fpl_data["element_types"]


# --- events ---------------------------------------------------------------

def test_get_events(fpl_data):
    assert events.get_events() == fpl_data["events"]


def test_get_event_by_id_found(fpl_data):
    assert events.get_event_by_id(1) == fpl_data["events"][0]


def test_get_event_by_id_not_found():
    assert events.get_event_by_id(999) is None


def test_get_current_event_refreshes_data(monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr(FplService, "get_fpl_api_data", fetch)

    result = asyncio.run(events.get_current_event())

    fetch.assert_awaited_once()
    assert isinstance(result, EventResponse)
    assert result.id == 2


def test_get_current_event_none_current(monkeypatch, loaded_service):
    monkeypatch.setattr(FplService, "get_fpl_api_data", AsyncMock())
    for event in loaded_service.fpl_data["events"]:
        event["is_current"] = False

    assert asyncio.run(events.get_current_event()) is None


def test_get_current_event_uses_cached_data_when_refresh_fails(monkeypatch):
    # A failed refresh is a no-op inside get_fpl_api_data, leaving cached data intact.
    monkeypatch.setattr(
        "src.util.fpl_service.requests.get",
        Mock(side_effect=requests.exceptions.ConnectionError("down")),
    )

    result = asyncio.run(events.get_current_event())

    assert result.id == 2


# --- teams ----------------------------------------------------------------

def test_get_teams(fpl_data):
    assert teams.get_teams() == fpl_data["teams"]


def test_get_team_by_name_found():
    assert teams.get_team_by_name("Arsenal") == {"id": 1, "name": "Arsenal"}


def test_get_team_by_name_not_found():
    assert teams.get_team_by_name("Nowhere FC") is None


def test_get_team_by_name_is_case_sensitive():
    assert teams.get_team_by_name("arsenal") is None


# --- data not loaded ------------------------------------------------------

@pytest.mark.parametrize(
    "call",
    [
        elements.get_elements,
        lambda: elements.get_element_by_id(1),
        lambda: elements.get_elements_by_type(3),
        elements.get_element_types,
        events.get_events,
        lambda: events.get_event_by_id(1),
        teams.get_teams,
        lambda: teams.get_team_by_name("Arsenal"),
    ],
)
def test_services_raise_when_data_not_loaded(loaded_service, call):
    loaded_service.fpl_data = None
    with pytest.raises(FplDataUnavailableError):
        call()
