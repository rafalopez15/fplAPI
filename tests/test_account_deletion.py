# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""Deleting an account: DELETE /api/me, services/profiles.py and util/supabase_admin.py."""
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
import requests
from sqlalchemy import func, select, text
from src.db.models import DeletedAccount, Note, Profile, UserTeam
from src.services import profiles
from src.util import fpl_client, supabase_admin
from tests.conftest import USER_ID, make_fpl_manager

OTHER_USER = uuid4()
SUPABASE = "https://test-ref.supabase.co"
NOTE = {"text": "Watch Isak", "created_at": "2026-11-06T10:00:00Z",
        "updated_at": "2026-11-06T10:00:00Z"}


@pytest.fixture
def supabase(monkeypatch):
    """The Admin API, configured and answering 204. Returns the requests.delete mock."""
    monkeypatch.setattr(supabase_admin, "SUPABASE_URL", SUPABASE)
    monkeypatch.setattr(supabase_admin, "SUPABASE_SECRET_KEY", "sb_secret_test")
    mock = Mock(return_value=Mock(ok=True, status_code=204))
    monkeypatch.setattr(supabase_admin.requests, "delete", mock)
    return mock


@pytest.fixture
def account(client, signed_in, monkeypatch):
    """USER_ID and OTHER_USER, each with a note and a team, made through the API.
    Requests default to USER_ID's token."""
    monkeypatch.setattr(fpl_client, "fetch_manager", Mock(return_value=make_fpl_manager()))
    for user in (USER_ID, OTHER_USER):
        headers = signed_in(user)
        assert client.put(f"/api/me/notes/{uuid4()}", json=NOTE, headers=headers).status_code == 200
        assert client.put("/api/me/teams/1", json={"relation": "mine"},
                          headers=headers).status_code == 200
    client.headers.update(signed_in())  # requests are USER_ID's from here on
    return client


def rows(session, model, user_id):
    column = model.id if model is Profile else model.user_id
    return session.scalar(select(func.count()).select_from(model).where(column == user_id))


# --- deleting ------------------------------------------------------------------

def test_deleting_removes_everything_the_account_owns(account, supabase,
                                                      seeded_session):
    response = account.delete("/api/me")
    assert response.status_code == 204
    assert response.content == b""
    user = UUID(USER_ID)
    assert [rows(seeded_session, m, user) for m in (Profile, Note, UserTeam)] == [0, 0, 0]
    assert seeded_session.get(DeletedAccount, user) is not None

    url = supabase.call_args.args[0]
    headers = supabase.call_args.kwargs["headers"]
    assert url == f"{SUPABASE}/auth/v1/admin/users/{USER_ID}"
    assert headers == {"apikey": "sb_secret_test", "Authorization": "Bearer sb_secret_test"}
    assert supabase.call_args.kwargs["timeout"] == supabase_admin.TIMEOUT


@pytest.mark.usefixtures("supabase")
def test_deleting_leaves_other_accounts_alone(account, seeded_session):
    account.delete("/api/me")
    assert [rows(seeded_session, m, OTHER_USER) for m in (Profile, Note, UserTeam)] == [1, 1, 1]


@pytest.mark.usefixtures("supabase")
def test_deleting_an_account_that_never_called_the_api(client, signed_in):
    # A sign-in with no profile yet still has a Supabase user to delete.
    assert client.delete("/api/me", headers=signed_in()).status_code == 204


def not_found(body):
    """A 404 from Supabase with this JSON body (or a body that isn't JSON)."""
    response = Mock(ok=False, status_code=404)
    if isinstance(body, Exception):
        response.json.side_effect = body
    else:
        response.json.return_value = body
    return response


# Supabase's answer for a user it doesn't have, as checked on staging.
USER_NOT_FOUND = {"code": 404, "error_code": "user_not_found", "msg": "User not found"}


def test_a_user_supabase_no_longer_has_counts_as_deleted(account, supabase):
    supabase.return_value = not_found(USER_NOT_FOUND)
    assert account.delete("/api/me").status_code == 204


@pytest.mark.parametrize("body", [
    {"message": "no Route matched with those values"},  # a wrong SUPABASE_URL path
    {"code": 404, "error_code": "not_found"},
    ["user_not_found"],
    ValueError("not JSON"),
])
def test_any_other_404_isnt_a_deletion(account, supabase, seeded_session, body):
    # Counting it as done would delete the notes but leave the email in Supabase.
    supabase.return_value = not_found(body)
    assert account.delete("/api/me").status_code == 503
    assert rows(seeded_session, Profile, UUID(USER_ID)) == 1


@pytest.mark.usefixtures("supabase")
def test_deleting_twice_is_204(account):
    # A retry after a lost response.
    for _ in range(2):
        assert account.delete("/api/me").status_code == 204


@pytest.mark.parametrize("failure", [
    Mock(return_value=Mock(ok=False, status_code=500)),
    Mock(return_value=Mock(ok=False, status_code=401)),  # a wrong secret key
    Mock(side_effect=requests.Timeout()),
    Mock(side_effect=requests.ConnectionError()),
])
def test_supabase_failing_changes_nothing(account, supabase, seeded_session,
                                          monkeypatch, failure):
    monkeypatch.setattr(supabase_admin.requests, "delete", failure)
    response = account.delete("/api/me")
    assert response.status_code == 503
    assert response.json() == {"detail": "Couldn't delete your account right now"}
    assert response.headers["cache-control"] == "private, no-store"
    user = UUID(USER_ID)
    assert [rows(seeded_session, m, user) for m in (Profile, Note, UserTeam)] == [1, 1, 1]
    assert seeded_session.get(DeletedAccount, user) is None
    assert supabase.call_count == 0  # the failing mock replaced it


def test_failures_are_logged_without_the_key(account, supabase, caplog):
    supabase.return_value = Mock(ok=False, status_code=401)
    account.delete("/api/me")
    assert f"Couldn't delete Supabase user {USER_ID}: Supabase answered 401" in caplog.text
    assert "sb_secret_test" not in caplog.text


@pytest.mark.parametrize("missing", ["SUPABASE_URL", "SUPABASE_SECRET_KEY"])
def test_without_the_secret_key_deleting_is_503(account, supabase, monkeypatch,
                                                seeded_session, missing):
    monkeypatch.setattr(supabase_admin, missing, None)
    assert account.delete("/api/me").status_code == 503
    supabase.assert_not_called()
    assert rows(seeded_session, Note, UUID(USER_ID)) == 1


@pytest.mark.usefixtures("jwks", "supabase")
def test_deleting_needs_a_token(client):
    assert client.delete("/api/me").status_code == 401


# --- after deleting ------------------------------------------------------------

@pytest.mark.usefixtures("supabase")
@pytest.mark.parametrize("method, path, body", [
    ("PUT", f"/api/me/notes/{uuid4()}", NOTE),  # a queued write flushed late
    ("PUT", "/api/me/teams/1", {"relation": "following"}),
    ("GET", "/api/me", None),
])
def test_a_deleted_accounts_token_cant_write(account, seeded_session,
                                              method, path, body):
    # The token still verifies for up to an hour after deletion.
    account.delete("/api/me")
    response = account.request(method, path, json=body)
    assert response.status_code == 401
    assert response.json() == {"detail": "Not signed in"}
    assert response.headers["www-authenticate"] == "Bearer"
    user = UUID(USER_ID)
    assert [rows(seeded_session, m, user) for m in (Profile, Note, UserTeam)] == [0, 0, 0]


@pytest.mark.usefixtures("supabase")
def test_a_deleted_accounts_reads_are_empty(account):
    account.delete("/api/me")
    assert account.get("/api/me/teams").json() == []
    assert account.get("/api/me/notes").json()["notes"] == []


def test_writes_take_the_account_lock(seeded_session):
    # So a write racing a deletion waits for it, then sees deleted_accounts.
    profiles.ensure_profile(seeded_session, uuid4())
    held = seeded_session.scalar(text(
        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
    ))
    assert held == 1
