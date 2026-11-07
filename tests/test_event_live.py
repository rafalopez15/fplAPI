# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""GET /api/events/{id}/live and its service, which call FPL live (mocked here)."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from main import app
from src.models.event import LiveElementResponse
from src.routers import events as events_router
from src.services import events
from src.util import fpl_client
from src.util.fpl_client import FplNotFoundError, FplUnavailableError
from tests.conftest import make_fpl_event_live


@pytest.fixture
def api():
    # The endpoint doesn't touch the database, so no seeded session is needed.
    return TestClient(app)


@pytest.fixture
def fetch(monkeypatch):
    mock = Mock(return_value=make_fpl_event_live())
    monkeypatch.setattr(fpl_client, "fetch_event_live", mock)
    return mock


# --- service -----------------------------------------------------------------


def test_get_live_service_flattens_the_stats(fetch):
    result = events.get_live(9)
    fetch.assert_called_once_with(9)
    assert all(isinstance(item, LiveElementResponse) for item in result)
    assert [(i.id, i.total_points, i.minutes) for i in result] == [
        (1, 5, 90),
        (2, 0, 12),
        (3, 0, 0),
    ]


def test_get_live_service_handles_missing_stats(fetch):
    fetch.return_value = {"elements": [{"id": 7}]}
    assert events.get_live(9) == [LiveElementResponse(id=7)]


def test_get_live_service_handles_missing_elements(fetch):
    fetch.return_value = {}
    assert not events.get_live(9)


# --- route -------------------------------------------------------------------


@pytest.mark.usefixtures("fetch")
def test_get_live(api):
    response = api.get("/api/events/9/live")
    assert response.status_code == 200
    body = response.json()
    assert body[0] == {"id": 1, "total_points": 5, "minutes": 90}
    assert (
        body[0].keys() == LiveElementResponse.model_fields.keys()
    )  # no explain or bps
    assert response.headers["cache-control"] == events_router.LIVE_CACHE


def test_get_live_for_a_gameweek_not_started(api, fetch):
    fetch.return_value = {"elements": []}
    response = api.get("/api/events/12/live")
    assert response.status_code == 200
    assert response.json() == []


def test_get_live_unknown_gameweek_returns_404(api, fetch):
    fetch.side_effect = FplNotFoundError("nope")
    response = api.get("/api/events/39/live")
    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}
    assert response.headers["cache-control"] == "no-store"


def test_get_live_fpl_unavailable_returns_503(api, fetch):
    fetch.side_effect = FplUnavailableError("timed out")
    response = api.get("/api/events/9/live")
    assert response.status_code == 503
    assert response.json() == {"detail": "FPL is unavailable right now"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("bad_id", ["0", "-1", "abc", "2147483648"])
def test_get_live_invalid_id_returns_422_without_calling_fpl(api, fetch, bad_id):
    assert api.get(f"/api/events/{bad_id}/live").status_code == 422
    fetch.assert_not_called()
