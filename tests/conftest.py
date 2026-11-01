# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
import os

# Config is read at import time, so make sure it exists before importing src.
# This keeps the suite independent of a local .env file (e.g. in CI).
os.environ.setdefault("FPL_BASE_URL", "https://fantasy.premierleague.com/api")
os.environ.setdefault("FPL_BOOTSTRAP_STATIC_PATH", "/bootstrap-static/")

import pytest  # pylint: disable=wrong-import-position
from src.util.fpl_service import FplService  # pylint: disable=wrong-import-position


def make_element(**overrides):
    element = {
        "element_type": 3,
        "event_points": 5,
        "first_name": "Bukayo",
        "form": "6.0",
        "id": 1,
        "news": "",
        "now_cost": 90,
        "points_per_game": "5.5",
        "second_name": "Saka",
        "selected_by_percent": "40.1",
        "status": "a",
        "team": 1,
        "team_code": 3,
        "total_points": 120,
        "web_name": "Saka",
    }
    element.update(overrides)
    return element


def make_event(**overrides):
    event = {
        "id": 1,
        "name": "Gameweek 1",
        "average_entry_score": 50,
        "highest_scoring_entry": 12345,
        "deadline_time_epoch": 1723818600,
        "deadline_time_game_offset": 0,
        "highest_score": 120,
        "most_selected": 1,
        "most_transferred_in": 2,
        "top_element": 1,
        "top_element_info": {"id": 1, "points": 20},
        "transfers_made": 0,
        "most_captained": 1,
        "most_vice_captained": 2,
        "is_current": False,
    }
    event.update(overrides)
    return event


@pytest.fixture
def fpl_data():
    return {
        "elements": [
            make_element(id=1, element_type=3, web_name="Saka"),
            make_element(id=2, element_type=4, web_name="Haaland"),
            make_element(id=3, element_type=3, web_name="Palmer"),
        ],
        "element_types": [
            {"id": 3, "singular_name": "Midfielder"},
            {"id": 4, "singular_name": "Forward"},
        ],
        "events": [
            make_event(id=1, name="Gameweek 1"),
            make_event(id=2, name="Gameweek 2", is_current=True),
        ],
        "teams": [
            {"id": 1, "name": "Arsenal"},
            {"id": 2, "name": "Man City"},
        ],
    }


@pytest.fixture
def loaded_service(fpl_data):
    """The FplService singleton pre-loaded with sample data."""
    service = FplService()
    service.fpl_data = fpl_data
    yield service
    service.fpl_data = None


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Fail loudly if any test reaches the real FPL API."""

    def _blocked(*args, **kwargs):
        raise AssertionError(f"Unexpected network call: {args} {kwargs}")

    monkeypatch.setattr("src.util.fpl_service.requests.get", _blocked)
