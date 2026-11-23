# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""GET /api/leagues/{id}/activity: what the gameweek pass stored for a league's
teams. FPL is called (mocked here) only to check a league before tracking it."""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import delete, func, select, update
from src.db.models import (
    Event,
    LeagueTeam,
    SyncRun,
    TeamGameweek,
    TrackedLeague,
    TrackedTeam,
)
from src.services import league_activity
from src.util import fpl_client
from src.util.fpl_client import FplNotFoundError, FplUnavailableError
from tests.conftest import make_fpl_league_standings, make_fpl_new_entry

PATH = "/api/leagues/5508/activity"
TEAM_A, TEAM_B = 7700093, 1


@pytest.fixture
def api(client, seeded_session):
    """The seeded gameweeks 8 and 9 past their deadline, 10 still to come."""
    seeded_session.execute(
        update(Event)
        .where(Event.id == 10)
        .values(deadline_time=func.now() + timedelta(days=1))
    )
    seeded_session.flush()
    return client


@pytest.fixture
def fetch(monkeypatch):
    mock = Mock(return_value=make_fpl_league_standings())
    monkeypatch.setattr(fpl_client, "fetch_league_standings", mock)
    return mock


def track(session, league_id=5508, teams=(), refreshed=True):
    """A tracked league with these (manager_id, name, last_event) teams."""
    session.add(
        TrackedLeague(
            league_id=league_id,
            last_requested_at=func.now() - timedelta(days=1),
            teams_updated_at=func.now() if refreshed else None,
        )
    )
    for manager_id, name, last_event in teams:
        session.add(
            TrackedTeam(manager_id=manager_id, name=name, last_event=last_event)
        )
    session.flush()
    session.add_all(LeagueTeam(league_id=league_id, manager_id=m) for m, _, _ in teams)
    session.flush()


def gameweek(session, manager_id, event=9, **fields):
    row = {
        "transfers": [],
        "transfers_cost": 0,
        "chip": None,
        "captain": 2,
        "vice_captain": 1,
        "captain_changed": False,
        **fields,
    }
    session.add(TeamGameweek(manager_id=manager_id, event=event, **row))
    session.flush()


def tracked_ids(session):
    return list(session.scalars(select(TrackedLeague.league_id)))


# --- a league seen for the first time --------------------------------------------


def test_a_new_league_is_tracked_and_pending(api, fetch, seeded_session):
    response = api.get(PATH)

    assert response.status_code == 200
    assert response.json() == {
        "league_id": 5508,
        "event": 9,
        "pending": True,
        "teams": [],
    }
    assert response.headers["cache-control"] == "s-maxage=300"
    fetch.assert_called_once_with(5508, 1)
    assert tracked_ids(seeded_session) == [5508]


@pytest.mark.parametrize(
    "standings",
    [
        make_fpl_league_standings(has_next=True),
        {
            **make_fpl_league_standings(results=[]),
            "new_entries": {
                "has_next": True,
                "page": 1,
                "results": [make_fpl_new_entry(8533420, "Kt")],
            },
        },
    ],
)
def test_a_league_over_one_page_is_too_big(api, fetch, seeded_session, standings):
    fetch.return_value = standings
    response = api.get(PATH)
    assert response.status_code == 422
    assert response.json() == {"detail": "League too big for activity"}
    assert response.headers["cache-control"] == "s-maxage=3600"
    assert not tracked_ids(seeded_session)


def test_an_unknown_league_is_404(api, fetch, seeded_session):
    fetch.side_effect = FplNotFoundError("league")
    response = api.get(PATH)
    assert response.status_code == 404
    assert response.json() == {"detail": "League not found"}
    assert response.headers["cache-control"] == "no-store"
    assert not tracked_ids(seeded_session)


def test_fpl_down_for_a_new_league_is_503(api, fetch, seeded_session):
    fetch.side_effect = FplUnavailableError("updating")
    response = api.get(PATH)
    assert response.status_code == 503
    assert response.json() == {"detail": "FPL is unavailable right now"}
    assert not tracked_ids(seeded_session)


# --- limits on tracking ----------------------------------------------------------


def add_leagues(session, count, created_ago, first=1000):
    session.add_all(
        TrackedLeague(league_id=first + n, created_at=func.now() - created_ago)
        for n in range(count)
    )
    session.flush()


@pytest.mark.parametrize(
    "count, created_ago",
    [
        (league_activity.LEAGUE_LIMIT, timedelta(days=2)),
        (league_activity.NEW_LEAGUE_LIMIT, timedelta(minutes=30)),
    ],
)
def test_past_a_limit_a_new_league_is_429(
    api, fetch, seeded_session, count, created_ago
):
    add_leagues(seeded_session, count, created_ago)

    response = api.get(PATH)

    assert response.status_code == 429
    assert response.headers["retry-after"] == "3600"
    assert response.headers["cache-control"] == "no-store"
    fetch.assert_not_called()
    assert 5508 not in tracked_ids(seeded_session)


@pytest.mark.usefixtures("fetch")
def test_just_under_both_limits_a_new_league_is_tracked(api, seeded_session):
    new = league_activity.NEW_LEAGUE_LIMIT - 1
    add_leagues(seeded_session, new, timedelta(minutes=30))
    add_leagues(
        seeded_session,
        league_activity.LEAGUE_LIMIT - 1 - new,
        timedelta(hours=2),
        first=5000,
    )
    assert api.get(PATH).status_code == 200


def test_a_tracked_league_answers_at_the_limit(api, fetch, seeded_session):
    track(seeded_session)
    add_leagues(seeded_session, league_activity.LEAGUE_LIMIT, timedelta(0))
    assert api.get(PATH).status_code == 200
    fetch.assert_not_called()


# --- a tracked league ------------------------------------------------------------


def test_a_tracked_league_is_read_without_calling_fpl(api, fetch, seeded_session):
    track(seeded_session, teams=[(TEAM_A, "Amos's Team", 9), (TEAM_B, "Solio", 9)])
    gameweek(
        seeded_session,
        TEAM_A,
        transfers=[{"element_in": 3, "element_out": 1}],
        transfers_cost=4,
        chip="wildcard",
        captain=3,
        captain_changed=True,
        points=71,
    )
    gameweek(seeded_session, TEAM_B)
    before = seeded_session.scalar(select(TrackedLeague.last_requested_at))

    response = api.get(PATH)

    assert response.status_code == 200
    assert response.json() == {
        "league_id": 5508,
        "event": 9,
        "pending": False,
        "teams": [
            {
                "entry": TEAM_B,
                "entry_name": "Solio",
                "event": 9,
                "transfers": [],
                "transfers_cost": 0,
                "chip": None,
                "captain": 2,
                "vice_captain": 1,
                "captain_changed": False,
                "points": None,
            },
            {
                "entry": TEAM_A,
                "entry_name": "Amos's Team",
                "event": 9,
                "transfers": [{"element_in": 3, "element_out": 1}],
                "transfers_cost": 4,
                "chip": "wildcard",
                "captain": 3,
                "vice_captain": 1,
                "captain_changed": True,
                "points": 71,
            },
        ],
    }
    fetch.assert_not_called()
    seeded_session.expire_all()
    assert seeded_session.scalar(select(TrackedLeague.last_requested_at)) > before


@pytest.mark.usefixtures("fetch")
def test_pending_while_a_team_is_behind_with_the_rest_listed(api, seeded_session):
    track(seeded_session, teams=[(TEAM_A, "Amos's Team", 9), (TEAM_B, "Solio", 8)])
    gameweek(seeded_session, TEAM_A)
    gameweek(seeded_session, TEAM_B, event=8)

    body = api.get(PATH).json()

    assert body["pending"] is True
    assert [team["entry"] for team in body["teams"]] == [TEAM_A]


@pytest.mark.usefixtures("fetch")
@pytest.mark.parametrize(
    "teams, refreshed",
    [([], False), ([(TEAM_A, "Amos's Team", None)], True)],
)
def test_pending_before_the_pass_reaches_the_league(
    api, seeded_session, teams, refreshed
):
    track(seeded_session, teams=teams, refreshed=refreshed)
    body = api.get(PATH).json()
    assert (body["pending"], body["teams"]) == (True, [])


@pytest.mark.usefixtures("fetch")
def test_an_empty_league_after_the_pass_is_not_pending(api, seeded_session):
    track(seeded_session)
    assert api.get(PATH).json()["pending"] is False


@pytest.mark.usefixtures("fetch")
def test_an_earlier_gameweek(api, seeded_session):
    track(seeded_session, teams=[(TEAM_A, "Amos's Team", 9)])
    gameweek(seeded_session, TEAM_A, event=8, captain=1, points=48)
    gameweek(seeded_session, TEAM_A, points=90)

    body = api.get(PATH, params={"event": 8}).json()

    assert (body["event"], body["pending"]) == (8, False)
    assert [(t["captain"], t["points"]) for t in body["teams"]] == [(1, 48)]


def test_real_names_never_leave_the_api(api, fetch, seeded_session):
    # FPL sends each manager's name on standings and new entries.
    fetch.return_value = make_fpl_league_standings(
        new_entries=[make_fpl_new_entry(8533420, "Kt")]
    )
    texts = [api.get(PATH).text]
    track(seeded_session, league_id=314, teams=[(TEAM_A, "Amos's Team", 9)])
    gameweek(seeded_session, TEAM_A)
    texts.append(api.get("/api/leagues/314/activity").text)
    for text in texts:
        assert "Chris" not in text and "Musson" not in text
        assert "player_name" not in text
        assert "player_first_name" not in text and "player_last_name" not in text


# --- gameweeks -------------------------------------------------------------------


@pytest.mark.parametrize(
    "event, detail",
    [(99, "Event not found"), (10, "Event deadline hasn't passed")],
)
def test_unknown_or_future_gameweeks_are_404(api, fetch, seeded_session, event, detail):
    response = api.get(PATH, params={"event": event})
    assert response.status_code == 404
    assert response.json() == {"detail": detail}
    assert response.headers["cache-control"] == "no-store"
    fetch.assert_not_called()
    assert not tracked_ids(seeded_session)


@pytest.mark.parametrize("event", [0, 2_147_483_648])
def test_an_invalid_gameweek_is_422(api, event):
    assert api.get(PATH, params={"event": event}).status_code == 422


def test_before_the_first_deadline_is_404(api, seeded_session):
    seeded_session.execute(
        update(Event).values(deadline_time=func.now() + timedelta(days=1))
    )
    seeded_session.flush()
    response = api.get(PATH)
    assert response.status_code == 404
    assert response.json() == {"detail": "Event deadline hasn't passed"}


def test_503_before_the_first_sync(api, seeded_session):
    seeded_session.execute(delete(SyncRun))
    seeded_session.flush()
    assert api.get(PATH).status_code == 503
