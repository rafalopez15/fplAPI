# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""The FPL teams on a user's account: /api/me/teams and services/user_teams.py."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from src.db.models import Profile, UserTeam
from src.services.user_teams import ADD_LIMIT, TEAM_LIMIT
from src.util import fpl_client
from src.util.fpl_client import FplNotFoundError, FplUnavailableError
from tests.conftest import USER_ID, make_fpl_manager

OTHER_USER = uuid4()


@pytest.fixture
def fetch_manager(monkeypatch):
    mock = Mock(return_value=make_fpl_manager())
    monkeypatch.setattr(fpl_client, "fetch_manager", mock)
    return mock


@pytest.fixture
def api(client, signed_in):
    """The client, with the signed-in user's headers on every request."""
    client.headers.update(signed_in())
    return client


def add_rows(session, user_id, *manager_ids, relation="following"):
    """Teams added straight to the database, a minute apart, oldest first.

    Dated 1 November 2026, too old for the hourly limit; see add_recent().
    """
    session.add(Profile(id=user_id))
    session.flush()
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    session.add_all(
        UserTeam(
            user_id=user_id,
            manager_id=manager_id,
            relation=relation,
            created_at=start + timedelta(minutes=i),
        )
        for i, manager_id in enumerate(manager_ids)
    )
    session.flush()


def teams(api):
    return [(t["manager_id"], t["relation"]) for t in api.get("/api/me/teams").json()]


# --- listing -------------------------------------------------------------------


def test_no_teams_is_an_empty_list(api):
    response = api.get("/api/me/teams")
    assert response.status_code == 200
    assert response.json() == []


def test_teams_are_newest_first(api, seeded_session):
    add_rows(seeded_session, UUID(USER_ID), 30, 10, 20)
    assert teams(api) == [(20, "following"), (10, "following"), (30, "following")]


def test_users_only_see_their_own_teams(client, signed_in, seeded_session):
    add_rows(seeded_session, OTHER_USER, 5)
    assert client.get("/api/me/teams", headers=signed_in()).json() == []
    assert [
        t["manager_id"]
        for t in client.get("/api/me/teams", headers=signed_in(OTHER_USER)).json()
    ] == [5]


# --- adding and switching ------------------------------------------------------


def test_adding_a_team_checks_fpl_and_saves_it(api, fetch_manager):
    response = api.put("/api/me/teams/1", json={"relation": "mine"})
    assert response.status_code == 200
    body = response.json()
    assert (body["manager_id"], body["relation"]) == (1, "mine")
    assert body["created_at"]
    fetch_manager.assert_called_once_with(1)
    assert teams(api) == [(1, "mine")]


def test_no_transaction_is_open_while_fpl_is_called(api, seeded_session, monkeypatch):
    def fetch(manager_id):
        assert not seeded_session.in_transaction()
        return make_fpl_manager(id=manager_id)

    monkeypatch.setattr(fpl_client, "fetch_manager", Mock(side_effect=fetch))
    assert api.put("/api/me/teams/1", json={"relation": "mine"}).status_code == 200


@pytest.mark.usefixtures("fetch_manager")
@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_team_id_too_big_for_postgres_is_422(api, method):
    response = api.request(
        method, "/api/me/teams/2147483648", json={"relation": "mine"}
    )
    assert response.status_code == 422


def test_adding_a_team_before_get_me_creates_the_profile(
    api, fetch_manager, seeded_session
):
    # The app may save a team before it ever calls /api/me.
    assert api.put("/api/me/teams/1", json={"relation": "following"}).status_code == 200
    assert seeded_session.get(Profile, UUID(USER_ID)) is not None
    fetch_manager.assert_called_once()


def test_switching_a_team_skips_fpl_and_keeps_created_at(api, fetch_manager):
    first = api.put("/api/me/teams/1", json={"relation": "following"}).json()
    fetch_manager.reset_mock()

    second = api.put("/api/me/teams/1", json={"relation": "mine"}).json()
    assert second["relation"] == "mine"
    assert second["created_at"] == first["created_at"]
    fetch_manager.assert_not_called()
    assert teams(api) == [(1, "mine")]


def test_unknown_team_is_404_and_not_saved(api, monkeypatch):
    monkeypatch.setattr(
        fpl_client, "fetch_manager", Mock(side_effect=FplNotFoundError())
    )
    response = api.put("/api/me/teams/999999999", json={"relation": "following"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Manager not found"}
    assert teams(api) == []


def test_fpl_down_is_503_and_not_saved(api, monkeypatch):
    monkeypatch.setattr(
        fpl_client, "fetch_manager", Mock(side_effect=FplUnavailableError())
    )
    response = api.put("/api/me/teams/1", json={"relation": "following"})
    assert response.status_code == 503
    assert response.json() == {"detail": "FPL is unavailable right now"}
    assert response.headers["cache-control"] == "private, no-store"
    assert teams(api) == []


@pytest.mark.usefixtures("fetch_manager")
@pytest.mark.parametrize("body", [{"relation": "friend"}, {"relation": None}, {}, None])
def test_invalid_relation_is_422(api, body):
    assert api.put("/api/me/teams/1", json=body).status_code == 422


@pytest.mark.usefixtures("fetch_manager")
def test_invalid_team_id_is_422(api):
    assert api.put("/api/me/teams/0", json={"relation": "mine"}).status_code == 422


def test_a_team_over_the_limit_is_409(api, fetch_manager, seeded_session):
    add_rows(seeded_session, UUID(USER_ID), *range(1, TEAM_LIMIT + 1))

    response = api.put(
        f"/api/me/teams/{TEAM_LIMIT + 1}", json={"relation": "following"}
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "Team limit reached"}
    fetch_manager.assert_not_called()
    # Switching a team already on the account still works at the limit.
    assert api.put("/api/me/teams/1", json={"relation": "mine"}).status_code == 200


def add_recent(session, user_id, count, minutes_ago=30):
    """count teams added minutes_ago, by the database's clock."""
    session.add(Profile(id=user_id))
    session.flush()
    added = session.scalar(select(func.now())) - timedelta(minutes=minutes_ago)
    session.add_all(
        UserTeam(user_id=user_id, manager_id=i, relation="following", created_at=added)
        for i in range(1, count + 1)
    )
    session.flush()


def test_too_many_new_teams_in_an_hour_is_429(api, fetch_manager, seeded_session):
    add_recent(seeded_session, UUID(USER_ID), ADD_LIMIT, minutes_ago=30)

    response = api.put("/api/me/teams/9999", json={"relation": "following"})
    assert response.status_code == 429
    assert response.json() == {"detail": "Too many teams added, try again later"}
    # The oldest add leaves the hour in 30 minutes.
    assert 30 * 60 - 5 <= int(response.headers["retry-after"]) <= 30 * 60
    assert response.headers["cache-control"] == "private, no-store"
    fetch_manager.assert_not_called()


@pytest.mark.usefixtures("fetch_manager")
def test_switching_a_relation_doesnt_count_toward_the_hourly_limit(api, seeded_session):
    add_recent(seeded_session, UUID(USER_ID), ADD_LIMIT)
    assert api.put("/api/me/teams/1", json={"relation": "mine"}).status_code == 200


@pytest.mark.usefixtures("fetch_manager")
def test_adds_older_than_an_hour_dont_count(api, seeded_session):
    add_recent(seeded_session, UUID(USER_ID), ADD_LIMIT, minutes_ago=61)
    response = api.put("/api/me/teams/9999", json={"relation": "following"})
    assert response.status_code == 200


@pytest.mark.usefixtures("fetch_manager")
def test_one_under_the_hourly_limit_can_still_add(api, seeded_session):
    add_recent(seeded_session, UUID(USER_ID), ADD_LIMIT - 1)
    response = api.put("/api/me/teams/9999", json={"relation": "following"})
    assert response.status_code == 200


def test_adds_sent_in_parallel_cant_get_past_the_limit(
    api, fetch_manager, seeded_session
):
    # 60 other adds land while this one waits on FPL.
    fetch_manager.side_effect = lambda _: add_recent(
        seeded_session, UUID(USER_ID), ADD_LIMIT
    )
    response = api.put("/api/me/teams/9999", json={"relation": "following"})
    assert response.status_code == 429
    assert seeded_session.get(UserTeam, (UUID(USER_ID), 9999)) is None


def test_a_double_tap_at_the_limit_isnt_refused(api, fetch_manager, seeded_session):
    # The other tap adds this team during the FPL call.
    add_recent(seeded_session, UUID(USER_ID), ADD_LIMIT - 1)

    def other_tap(manager_id):
        seeded_session.add(
            UserTeam(user_id=UUID(USER_ID), manager_id=manager_id, relation="mine")
        )
        seeded_session.flush()

    fetch_manager.side_effect = other_tap
    response = api.put("/api/me/teams/9999", json={"relation": "following"})
    assert response.status_code == 200
    assert response.json()["relation"] == "following"


def test_the_hourly_limit_is_per_account(
    client, signed_in, fetch_manager, seeded_session
):
    add_recent(seeded_session, OTHER_USER, ADD_LIMIT)
    response = client.put(
        "/api/me/teams/9999", json={"relation": "following"}, headers=signed_in()
    )
    assert response.status_code == 200
    fetch_manager.assert_called_once_with(9999)


# --- removing ------------------------------------------------------------------


def test_removing_a_team(api, seeded_session):
    add_rows(seeded_session, UUID(USER_ID), 1, 2)
    response = api.delete("/api/me/teams/1")
    assert response.status_code == 204
    assert response.content == b""
    assert teams(api) == [(2, "following")]


def test_removing_a_team_that_isnt_there_is_204(api):
    assert api.delete("/api/me/teams/1").status_code == 204


def test_removing_only_touches_your_own_teams(client, signed_in, seeded_session):
    add_rows(seeded_session, OTHER_USER, 1)
    assert client.delete("/api/me/teams/1", headers=signed_in()).status_code == 204
    assert seeded_session.scalars(select(UserTeam.manager_id)).all() == [1]


# --- table ---------------------------------------------------------------------


def test_deleting_a_profile_deletes_its_teams(seeded_session):
    add_rows(seeded_session, OTHER_USER, 1, 2)
    seeded_session.delete(seeded_session.get(Profile, OTHER_USER))
    seeded_session.flush()
    seeded_session.expire_all()
    assert seeded_session.scalars(select(UserTeam)).all() == []


def test_relation_must_be_mine_or_following(seeded_session):
    seeded_session.add(Profile(id=OTHER_USER))
    seeded_session.flush()
    seeded_session.add(UserTeam(user_id=OTHER_USER, manager_id=1, relation="friend"))
    with pytest.raises(IntegrityError):
        seeded_session.flush()


def test_a_team_needs_a_profile(seeded_session):
    seeded_session.add(UserTeam(user_id=uuid4(), manager_id=1, relation="mine"))
    with pytest.raises(IntegrityError):
        seeded_session.flush()
