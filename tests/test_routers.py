# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session
from main import app
from src.db.models import Element, Event, Fixture, SyncRun, Team
from src.models.element import ElementResponse
from src.models.event import EventResponse
from src.models.fixture import FixtureResponse
from src.models.team import TeamResponse
from src.util import database


def update_row(session, model, row_id, **values):
    row = session.get(model, row_id)
    for name, value in values.items():
        setattr(row, name, value)
    session.flush()


# --- elements -------------------------------------------------------------

def test_get_elements(client):
    response = client.get("/api/elements")
    assert response.status_code == 200
    assert [e["web_name"] for e in response.json()] == ["Saka", "Haaland", "Palmer"]


def test_get_elements_uses_response_model(client):
    element = client.get("/api/elements").json()[0]
    assert element.keys() == ElementResponse.model_fields.keys()
    assert "updated_at" not in element


def test_element_decimals_are_numbers(client):
    element = client.get("/api/elements/1").json()
    assert element["form"] == 6.0
    assert element["selected_by_percent"] == 40.1
    assert element["expected_goals"] == 3.21


def test_element_nullable_fields(client, seeded_session):
    update_row(
        seeded_session, Element, 1,
        chance_of_playing_next_round=75,
        news_added=datetime(2026, 10, 20, 10, 30, 12, 123456, tzinfo=timezone.utc),
        ep_next=None,
    )
    element = client.get("/api/elements/1").json()
    assert element["chance_of_playing_next_round"] == 75
    assert element["chance_of_playing_this_round"] is None
    assert element["news_added"] == "2026-10-20T10:30:12.123456Z"
    assert element["ep_next"] is None


def test_element_selection_flags(client, seeded_session):
    update_row(seeded_session, Element, 1, can_select=False, status="u")
    element = client.get("/api/elements/1").json()
    assert element["can_select"] is False
    assert element["can_transact"] is True
    assert element["removed"] is False


def test_unselectable_players_are_not_filtered_out(client, seeded_session):
    update_row(seeded_session, Element, 1, can_select=False)
    assert len(client.get("/api/elements").json()) == 3


def test_get_elements_empty(client, seeded_session):
    seeded_session.execute(delete(Element))
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

def test_get_events(client):
    response = client.get("/api/events")
    assert response.status_code == 200
    body = response.json()
    assert [e["id"] for e in body] == [8, 9, 10]
    assert body[0].keys() == EventResponse.model_fields.keys()


def test_get_events_empty(client, seeded_session):
    seeded_session.execute(delete(Fixture))
    seeded_session.execute(delete(Event))
    response = client.get("/api/events")
    assert response.status_code == 200
    assert response.json() == []


def test_get_event_by_id(client):
    response = client.get("/api/events/9")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Gameweek 9"
    assert body["deadline_time"] == "2026-10-31T11:00:00Z"
    assert body["chip_plays"] == [{"chip_name": "bboost", "num_played": 814606}]


def test_future_event_has_null_stats(client):
    body = client.get("/api/events/10").json()
    assert body["most_selected"] is None
    assert body["top_element_info"] is None


def test_get_event_by_id_not_found(client):
    response = client.get("/api/events/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def test_get_current_event(client):
    response = client.get("/api/events/current-event/")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 9
    assert body["is_current"] is True
    assert body["top_element_info"] == {"id": 2, "points": 17}


def test_get_current_event_not_found(client, seeded_session):
    update_row(seeded_session, Event, 9, is_current=False)
    response = client.get("/api/events/current-event/")
    assert response.status_code == 404
    assert response.json() == {"detail": "Current event not found"}


# --- teams ----------------------------------------------------------------

def test_get_teams(client):
    response = client.get("/api/teams")
    assert response.status_code == 200
    body = response.json()
    assert [t["name"] for t in body] == ["Arsenal", "Man City"]
    assert body[0].keys() == TeamResponse.model_fields.keys()
    assert "pulse_id" not in body[0]  # FPL sends it, but it isn't stored


def test_get_teams_empty(client, seeded_session):
    seeded_session.execute(delete(Fixture))
    seeded_session.execute(delete(Element))
    seeded_session.execute(delete(Team))
    response = client.get("/api/teams")
    assert response.status_code == 200
    assert response.json() == []


def test_get_team_by_name(client):
    response = client.get("/api/teams/Man City")
    assert response.status_code == 200
    assert response.json()["short_name"] == "MCI"


def test_get_team_by_name_not_found(client):
    response = client.get("/api/teams/Nowhere")
    assert response.status_code == 404
    assert response.json() == {"detail": "Team not found"}


# --- fixtures -------------------------------------------------------------

def test_get_fixtures_in_kickoff_order_with_postponed_last(client):
    response = client.get("/api/fixtures")
    assert response.status_code == 200
    assert [f["id"] for f in response.json()] == [71, 95, 91, 85]


def test_fixture_shape(client):
    body = client.get("/api/fixtures").json()
    assert body[0].keys() == FixtureResponse.model_fields.keys()
    assert body[0] == {
        "id": 71, "event": 8, "team_h": 1, "team_a": 2,
        "team_h_difficulty": 5, "team_a_difficulty": 4,
        "kickoff_time": "2026-10-25T15:00:00Z", "started": True, "finished": True,
        "team_h_score": 2, "team_a_score": 1,
    }


def test_postponed_fixture_has_null_event_and_kickoff(client):
    postponed = client.get("/api/fixtures").json()[-1]
    assert postponed["id"] == 85
    assert (postponed["event"], postponed["kickoff_time"]) == (None, None)
    assert (postponed["team_h_score"], postponed["team_a_score"]) == (None, None)


@pytest.mark.parametrize(
    "query, ids",
    [
        ("finished=false", [95, 91, 85]),  # includes 95: played, not yet confirmed
        ("finished=true", [71]),
        ("finished=0", [95, 91, 85]),
        ("started=false", [91, 85]),  # still to be played
        ("started=true", [71, 95]),
        ("started=true&finished=false", [95]),
    ],
)
def test_get_fixtures_filtered(client, query, ids):
    response = client.get(f"/api/fixtures?{query}")
    assert response.status_code == 200
    assert [f["id"] for f in response.json()] == ids


@pytest.mark.parametrize("query", ["finished=maybe", "started=soon"])
def test_get_fixtures_invalid_filter(client, query):
    assert client.get(f"/api/fixtures?{query}").status_code == 422


def test_get_fixtures_empty(client, seeded_session):
    seeded_session.execute(delete(Fixture))
    response = client.get("/api/fixtures")
    assert response.status_code == 200
    assert response.json() == []


# --- data unavailable -----------------------------------------------------

DATA_PATHS = [
    "/api/elements",
    "/api/elements/1",
    "/api/elements/position/3",
    "/api/events",
    "/api/events/1",
    "/api/events/current-event/",
    "/api/teams",
    "/api/teams/Arsenal",
    "/api/fixtures",
]


@pytest.mark.parametrize("path", DATA_PATHS)
def test_returns_503_before_the_first_sync(client, seeded_session, path):
    seeded_session.execute(delete(SyncRun))
    response = client.get(path)
    assert response.status_code == 503
    assert response.json() == {"detail": "FPL data is currently unavailable"}


def test_failed_syncs_alone_still_return_503(client, seeded_session):
    seeded_session.execute(delete(SyncRun))
    seeded_session.add(SyncRun(kind="bootstrap", status="failed"))
    assert client.get("/api/teams").status_code == 503


@pytest.mark.parametrize("path", DATA_PATHS)
def test_returns_503_when_the_database_is_unreachable(client, path):
    unreachable = create_engine("postgresql+psycopg://x:x@localhost:1/x")

    def get_session():
        with Session(unreachable) as session:
            yield session

    app.dependency_overrides[database.get_session] = get_session
    response = client.get(path)
    assert response.status_code == 503
    assert response.json() == {"detail": "FPL data is currently unavailable"}
