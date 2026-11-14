# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""fplapi_app, the restricted role the deployed API connects as."""

from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from src.db.models import Base, FplSnapshot, Note, Profile, UserTeam
from src.services import snapshots
from src.util import database, fpl_client, supabase_admin
from tests.conftest import USER_ID, make_fpl_manager
from tests.test_snapshots import PAYLOADS, ROUTES

ROLE = "fplapi_app"

# Every table, and what the role may do to it. A new table fails the first test
# until it's listed here, with a grant and a policy in its migration (or none).
PRIVILEGES = {
    "alembic_version": set(),
    "teams": {"SELECT"},
    "element_types": set(),
    "elements": {"SELECT"},
    "events": {"SELECT"},
    "fixtures": {"SELECT"},
    "player_fixture_history": set(),
    "element_event_points": {"SELECT"},
    "sync_runs": {"SELECT"},
    "profiles": {"SELECT", "INSERT", "DELETE"},
    "deleted_accounts": {"SELECT", "INSERT"},
    "user_teams": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "teams_tracked": {"SELECT", "INSERT", "UPDATE"},
    "notes": {"SELECT", "INSERT", "UPDATE"},
    "fpl_snapshots": {"SELECT", "INSERT", "UPDATE"},
}

NOTE = {
    "text": "Watch Isak",
    "created_at": "2026-11-06T10:00:00Z",
    "updated_at": "2026-11-06T10:00:00Z",
}


@pytest.fixture
def as_api_role(seeded_session):
    """The seeded session, switched to the API's role until the test ends."""
    seeded_session.execute(text(f"SET LOCAL ROLE {ROLE}"))
    # Releases the savepoint, so a later rollback in the code under test keeps it.
    seeded_session.commit()
    return seeded_session


@pytest.fixture
def fpl(monkeypatch):
    for name, build in PAYLOADS.items():
        monkeypatch.setattr(fpl_client, name, Mock(return_value=build()))


# --- grants and policies -----------------------------------------------------


def test_privileges_on_every_table(db_engine):
    with db_engine.connect() as connection:
        tables = connection.scalars(
            text(
                "SELECT relname FROM pg_class "
                "WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace"
            )
        ).all()
        granted = connection.execute(
            text(
                "SELECT table_name, privilege_type "
                "FROM information_schema.role_table_grants "
                "WHERE grantee = :role AND table_schema = 'public'"
            ),
            {"role": ROLE},
        ).all()
    assert set(tables) == set(PRIVILEGES) == {"alembic_version", *Base.metadata.tables}
    actual = {table: set() for table in tables}
    for table, privilege in granted:
        actual[table].add(privilege)
    assert actual == PRIVILEGES


def test_every_granted_table_has_a_policy(db_engine):
    with db_engine.connect() as connection:
        policies = connection.scalars(
            text("SELECT tablename FROM pg_policies WHERE :role = ANY(roles)"),
            {"role": ROLE},
        ).all()
    assert sorted(policies) == sorted(t for t, p in PRIVILEGES.items() if p)


def test_role_settings(db_engine):
    with db_engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolcanlogin, rolsuper, rolcreaterole, rolcreatedb, "
                "rolbypassrls, rolconfig FROM pg_roles WHERE rolname = :role"
            ),
            {"role": ROLE},
        ).one()
    assert role.rolcanlogin
    assert not (
        role.rolsuper or role.rolcreaterole or role.rolcreatedb or role.rolbypassrls
    )
    assert role.rolconfig == ["statement_timeout=10s"]


# --- what the role can't do --------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE intruder (id int)",
        "DROP TABLE notes",
        "ALTER TABLE notes ADD COLUMN intruder int",
        "UPDATE events SET name = 'x'",
        "DELETE FROM elements",
        "INSERT INTO sync_runs (kind, status) VALUES ('bootstrap', 'succeeded')",
        "SELECT * FROM element_types",
        "DELETE FROM fpl_snapshots",
    ],
)
def test_role_is_refused(as_api_role, statement):
    with pytest.raises(ProgrammingError, match="permission denied|must be owner"):
        as_api_role.execute(text(statement))


def test_the_snapshot_purge_needs_the_owner(as_api_role):
    with pytest.raises(ProgrammingError, match="permission denied"):
        snapshots.purge(as_api_role)


# --- the API's routes, as the role -------------------------------------------


@pytest.mark.parametrize(
    "path", ["/api/teams", "/api/elements", "/api/events", "/api/fixtures"]
)
@pytest.mark.usefixtures("as_api_role")
def test_synced_routes_read_the_data(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()


def test_healthcheck_reads_the_last_syncs(as_api_role):
    # /healthcheck opens its own session, so this runs its query directly.
    assert database.last_successful_sync(as_api_role, "bootstrap") is not None
    assert database.last_successful_sync(as_api_role, "event_points") is None


@pytest.mark.usefixtures("fpl")
@pytest.mark.parametrize("path, _fetch, key", ROUTES)
def test_live_routes_save_snapshots(client, as_api_role, path, _fetch, key):
    assert client.get(path).status_code == 200
    assert key in set(as_api_role.scalars(select(FplSnapshot.key)))


def test_an_account_from_first_call_to_deletion(
    client, as_api_role, signed_in, monkeypatch
):
    monkeypatch.setattr(
        fpl_client, "fetch_manager", Mock(return_value=make_fpl_manager())
    )
    client.headers.update(signed_in())
    note_id = uuid4()

    assert client.get("/api/me").status_code == 200
    assert client.put(f"/api/me/notes/{note_id}", json=NOTE).status_code == 200
    updated = {**NOTE, "updated_at": "2026-11-07T10:00:00Z"}
    assert client.put(f"/api/me/notes/{note_id}", json=updated).status_code == 200
    assert client.get("/api/me/notes").json()["notes"]
    response = client.delete(
        f"/api/me/notes/{note_id}", params={"updated_at": "2026-11-08T10:00:00Z"}
    )
    assert response.status_code == 204
    for relation in ("mine", "following"):
        response = client.put("/api/me/teams/1", json={"relation": relation})
        assert response.status_code == 200
    assert client.get("/api/me/teams").json()
    assert client.delete("/api/me/teams/1").status_code == 204
    assert client.put("/api/me/teams/1", json={"relation": "mine"}).status_code == 200

    monkeypatch.setattr(supabase_admin, "SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setattr(supabase_admin, "SUPABASE_SECRET_KEY", "sb_secret_test")
    monkeypatch.setattr(
        supabase_admin.requests,
        "delete",
        Mock(return_value=Mock(ok=True, status_code=204)),
    )
    assert client.delete("/api/me").status_code == 204
    # The cascade from profiles reaches tables the role can't delete from.
    for model, column in ((Profile, Profile.id), (Note, Note.user_id)):
        assert not as_api_role.scalars(select(model).where(column == USER_ID)).all()
    assert not as_api_role.scalars(
        select(UserTeam).where(UserTeam.user_id == USER_ID)
    ).all()
    # A deleted account can't write again.
    assert client.put(f"/api/me/notes/{uuid4()}", json=NOTE).status_code == 401
