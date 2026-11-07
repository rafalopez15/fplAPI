# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
import re
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from src.db.models import Event, Team
from src.models.element import ElementResponse
from src.models.event import EventResponse
from src.models.fixture import FixtureResponse
from src.models.team import TeamResponse
from src.services import elements, events, fixtures, teams
from tests.conftest import make_element, make_event


@pytest.fixture
def session(seeded_session):
    return seeded_session


# --- elements -------------------------------------------------------------


def test_get_elements(session):
    result = elements.get_elements(session)
    assert all(isinstance(e, ElementResponse) for e in result)
    assert [e.web_name for e in result] == ["Saka", "Haaland", "Palmer"]


def test_get_elements_decimals_become_floats(session):
    haaland = elements.get_element_by_id(session, 2)
    assert haaland.form == 8.1
    assert isinstance(haaland.form, float)


def test_get_element_by_id_found(session):
    result = elements.get_element_by_id(session, 2)
    assert isinstance(result, ElementResponse)
    assert result.web_name == "Haaland"


def test_get_element_by_id_not_found(session):
    assert elements.get_element_by_id(session, 999) is None


@pytest.mark.parametrize(
    "field", ["id", "web_name", "team", "element_type", "now_cost", "status"]
)
def test_element_missing_required_field_raises(field):
    element = make_element()
    del element[field]
    with pytest.raises(ValidationError):
        ElementResponse(**element)


def test_get_elements_by_type(session):
    result = elements.get_elements_by_type(session, 3)
    assert [e.web_name for e in result] == ["Saka", "Palmer"]


def test_get_elements_by_type_no_match(session):
    assert not elements.get_elements_by_type(session, 1)


# --- events ---------------------------------------------------------------


def test_get_events(session):
    result = events.get_events(session)
    assert all(isinstance(e, EventResponse) for e in result)
    assert [e.id for e in result] == [8, 9, 10]


def test_get_event_by_id_found(session):
    result = events.get_event_by_id(session, 9)
    assert result.name == "Gameweek 9"
    assert result.deadline_time == datetime(2026, 10, 31, 11, tzinfo=timezone.utc)


def test_get_event_by_id_not_found(session):
    assert events.get_event_by_id(session, 999) is None


def test_event_rebuilds_top_element_info(session):
    result = events.get_event_by_id(session, 9)
    assert result.top_element_info.model_dump() == {"id": 2, "points": 17}
    assert result.chip_plays[0].chip_name == "bboost"


def test_future_event_has_null_stats(session):
    result = events.get_event_by_id(session, 10)
    assert result.top_element_info is None
    assert result.most_selected is None
    assert result.chip_plays == []


def test_event_response_from_fpl_dict():
    # Built from FPL's own data, top_element_info is already in the right shape.
    event = EventResponse.model_validate(make_event())
    assert event.top_element_info.model_dump() == {"id": 2, "points": 17}


def test_get_current_event(session):
    assert events.get_current_event(session).id == 9


def test_get_current_event_none_current(session):
    for event in session.scalars(select(Event)):
        event.is_current = False
    assert events.get_current_event(session) is None


# --- teams ----------------------------------------------------------------


def test_get_teams(session):
    result = teams.get_teams(session)
    assert all(isinstance(t, TeamResponse) for t in result)
    assert [t.name for t in result] == ["Arsenal", "Man City"]


def test_get_team_by_name_found(session):
    result = teams.get_team_by_name(session, "Man City")
    assert (result.id, result.short_name) == (2, "MCI")


def test_get_team_by_name_not_found(session):
    assert teams.get_team_by_name(session, "Nowhere FC") is None


def test_get_team_by_name_is_case_sensitive(session):
    assert teams.get_team_by_name(session, "arsenal") is None


def test_teams_have_kit_colors(session):
    arsenal = teams.get_teams(session)[0]
    assert (arsenal.primary_color, arsenal.secondary_color) == ("#EF0107", "#FFFFFF")
    assert teams.get_team_by_name(session, "Man City").primary_color == "#6CABDD"


def test_team_without_kit_colors_gets_null(session):
    session.get(Team, 1).code = 999  # e.g. a promoted club not added yet
    session.flush()
    arsenal = teams.get_teams(session)[0]
    assert (arsenal.primary_color, arsenal.secondary_color) == (None, None)


def test_kit_colors_cover_a_full_league_in_hex():
    assert len(teams.KIT_COLORS) == 20
    for colors in teams.KIT_COLORS.values():
        assert all(re.fullmatch(r"#[0-9A-F]{6}", color) for color in colors), colors


# --- fixtures -------------------------------------------------------------


def test_get_fixtures(session):
    result = fixtures.get_fixtures(session)
    assert all(isinstance(f, FixtureResponse) for f in result)
    assert [f.id for f in result] == [71, 95, 91, 85]


def test_get_fixtures_upcoming(session):
    assert [f.id for f in fixtures.get_fixtures(session, finished=False)] == [
        95,
        91,
        85,
    ]


def test_get_fixtures_not_started(session):
    assert [f.id for f in fixtures.get_fixtures(session, started=False)] == [91, 85]


def test_get_fixtures_finished(session):
    [fixture] = fixtures.get_fixtures(session, finished=True)
    assert (fixture.id, fixture.team_h_score, fixture.team_a_score) == (71, 2, 1)
    assert fixture.kickoff_time == datetime(2026, 10, 25, 15, tzinfo=timezone.utc)
