# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""Staging's test users: src/jobs/manage_test_users.py."""

from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
import requests
from sqlalchemy import func, select
from src.db.models import DeletedAccount, Note, Profile, UserTeam
from src.jobs import manage_test_users as job
from src.util import database, supabase_admin

STAGING = f"https://{job.STAGING_REF}.supabase.co"
STAGING_DB = f"postgresql+psycopg://postgres.{job.STAGING_REF}:pw@pooler:5432/postgres"
TEST_ID = str(uuid4())
OTHER_TEST_ID = str(uuid4())
REAL_ID = str(uuid4())


class FakeAdmin:
    """Supabase's Auth Admin API in memory: users, and every call made."""

    def __init__(self, users=None):
        self.users = list(users or [])
        self.calls = []
        self.deleted = None  # supabase_admin's requests.delete, set by the fixture

    def request(self, method, url, **kwargs):
        path = url.split("/auth/v1/admin/", 1)[1]
        self.calls.append((method, path, kwargs.get("json")))
        if method == "GET":
            page, size = kwargs["params"]["page"], kwargs["params"]["per_page"]
            body = {"users": self.users[(page - 1) * size : page * size]}
        elif method == "POST":
            body = {"id": str(uuid4()), **kwargs["json"]}
            self.users.append(body)
        else:
            body = {}
        return Mock(ok=True, status_code=200, json=Mock(return_value=body))


@pytest.fixture
def admin(monkeypatch):
    """Staging configured, with two test users and one real user."""
    monkeypatch.setattr(job, "SUPABASE_URL", STAGING)
    monkeypatch.setattr(job, "SUPABASE_SECRET_KEY", "sb_secret_test")
    monkeypatch.setattr(job, "DATABASE_URL", STAGING_DB)
    monkeypatch.setenv("TEST_USER_PASSWORD", "shared-test-password")
    fake = FakeAdmin(
        [
            {"id": TEST_ID, "email": "test@fplsocial.dev"},
            {"id": OTHER_TEST_ID, "email": "ios@fplsocial.dev"},
            {"id": REAL_ID, "email": "someone@gmail.com"},
        ]
    )
    monkeypatch.setattr(job.requests, "request", fake.request)
    # delete_account() deletes the Supabase user through supabase_admin.
    monkeypatch.setattr(supabase_admin, "SUPABASE_URL", STAGING)
    monkeypatch.setattr(supabase_admin, "SUPABASE_SECRET_KEY", "sb_secret_test")
    deleted = Mock(return_value=Mock(ok=True, status_code=204))
    monkeypatch.setattr(supabase_admin.requests, "delete", deleted)
    fake.deleted = deleted
    return fake


@pytest.fixture
def session(db_session, monkeypatch):
    """main() opens Session(database.engine); give it the test database's session."""
    monkeypatch.setattr(job, "Session", Mock(return_value=_Same(db_session)))
    return db_session


class _Same:
    """A context manager that hands back an existing session without closing it."""

    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False


def with_data(session, *user_ids):
    """A profile, a note and a team for each user, committed as the API would save
    them, so a rolled-back deletion leaves them in place."""
    for user_id in map(UUID, user_ids):
        session.add(Profile(id=user_id))
        session.flush()
        session.add(UserTeam(user_id=user_id, manager_id=1, relation="mine"))
        session.add(
            Note(
                id=uuid4(),
                user_id=user_id,
                text="Watch Isak",
                players=[],
                created_at=func.now(),
                updated_at=func.now(),
                synced_at=func.now(),
            )
        )
    session.commit()


def rows(session, model, user_id):
    column = model.id if model is Profile else model.user_id
    return session.scalar(
        select(func.count()).select_from(model).where(column == UUID(user_id))
    )


def run(*argv):
    return job.main(list(argv))


# --- create --------------------------------------------------------------------


def test_create_makes_a_confirmed_user(admin, capsys):
    assert run("create", "--email", "new@fplsocial.dev") == 0
    assert (
        "POST",
        "users",
        {
            "email": "new@fplsocial.dev",
            "password": "shared-test-password",
            "email_confirm": True,
        },
    ) in admin.calls
    assert capsys.readouterr().out.strip() == "Created new@fplsocial.dev"


def test_create_an_existing_user_resets_its_password(admin, capsys):
    assert run("create") == 0  # the default email, which exists
    assert (
        "PUT",
        f"users/{TEST_ID}",
        {"password": "shared-test-password", "email_confirm": True},
    ) in admin.calls
    assert not [c for c in admin.calls if c[0] == "POST"]
    assert "Reset the password of test@fplsocial.dev" in capsys.readouterr().out


def test_create_without_the_shared_password_is_refused(admin, monkeypatch):
    monkeypatch.delenv("TEST_USER_PASSWORD")
    assert run("create") == 2
    assert not admin.calls


def test_emails_are_matched_ignoring_case(admin):
    assert run("create", "--email", "TEST@FPLsocial.dev") == 0
    assert admin.calls[-1][:2] == ("PUT", f"users/{TEST_ID}")


@pytest.mark.usefixtures("admin")
def test_create_never_prints_the_password_or_key(capsys):
    run("create", "--email", "new@fplsocial.dev")
    out = capsys.readouterr().out
    assert "shared-test-password" not in out
    assert "sb_secret_test" not in out


# --- delete and clear ------------------------------------------------------------


def test_delete_removes_the_user_and_their_data(admin, session):
    with_data(session, TEST_ID, REAL_ID)
    assert run("delete") == 0
    assert [rows(session, m, TEST_ID) for m in (Profile, UserTeam, Note)] == [0, 0, 0]
    assert session.get(DeletedAccount, UUID(TEST_ID)) is not None
    assert admin.deleted.call_args.args[0] == f"{STAGING}/auth/v1/admin/users/{TEST_ID}"
    assert rows(session, Profile, REAL_ID) == 1


@pytest.mark.usefixtures("session")
def test_deleting_a_user_that_doesnt_exist_changes_nothing(admin, capsys):
    assert run("delete", "--email", "gone@fplsocial.dev") == 0
    admin.deleted.assert_not_called()
    assert "No user gone@fplsocial.dev" in capsys.readouterr().out


def test_clear_deletes_only_test_users(admin, session, capsys):
    with_data(session, TEST_ID, OTHER_TEST_ID, REAL_ID)
    assert run("clear", "--confirm", "CLEAR") == 0
    for user_id in (TEST_ID, OTHER_TEST_ID):
        assert rows(session, Profile, user_id) == 0
    assert rows(session, Profile, REAL_ID) == 1
    deleted = {call.args[0].rsplit("/", 1)[1] for call in admin.deleted.call_args_list}
    assert deleted == {TEST_ID, OTHER_TEST_ID}
    assert capsys.readouterr().out.strip() == (
        "Cleared 2 test user(s)\n- ios@fplsocial.dev\n- test@fplsocial.dev"
    )


@pytest.mark.usefixtures("session")
@pytest.mark.parametrize("confirm", [[], ["--confirm", "clear"], ["--confirm", "yes"]])
def test_clear_without_the_confirmation_is_refused(admin, confirm):
    assert run("clear", *confirm) == 2
    assert not admin.calls
    admin.deleted.assert_not_called()


def test_users_are_read_page_by_page(admin, session, monkeypatch):
    monkeypatch.setattr(job, "PAGE_SIZE", 1)
    with_data(session, OTHER_TEST_ID)
    assert run("clear", "--confirm", "CLEAR") == 0
    pages = [c for c in admin.calls if c[0] == "GET"]
    assert len(pages) == 4  # three users, then an empty page
    assert rows(session, Profile, OTHER_TEST_ID) == 0


# --- guards --------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        ("SUPABASE_URL", "https://production-ref.supabase.co"),
        ("SUPABASE_URL", None),
        ("DATABASE_URL", "postgresql+psycopg://postgres.production-ref:pw@pooler/db"),
    ],
)
@pytest.mark.parametrize(
    "argv", [["create"], ["delete"], ["clear", "--confirm", "CLEAR"]]
)
def test_anything_but_staging_is_refused(admin, monkeypatch, capsys, override, argv):
    monkeypatch.setattr(job, *override)
    assert run(*argv) == 2
    assert not admin.calls
    admin.deleted.assert_not_called()
    assert "Refused" in capsys.readouterr().out


@pytest.mark.parametrize(
    "email", ["someone@gmail.com", "@fplsocial.dev", "a@fplsocial.dev.evil.com"]
)
@pytest.mark.parametrize("action", ["create", "delete"])
def test_emails_outside_the_test_domain_are_refused(admin, action, email):
    assert run(action, "--email", email) == 2
    assert not admin.calls
    admin.deleted.assert_not_called()


# --- failures and output -----------------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        Mock(return_value=Mock(ok=False, status_code=401)),
        Mock(side_effect=requests.ConnectionError()),
    ],
)
@pytest.mark.usefixtures("admin")
def test_supabase_failing_is_exit_1_without_the_key(monkeypatch, capsys, failure):
    monkeypatch.setattr(job.requests, "request", failure)
    assert run("create") == 1
    out = capsys.readouterr().out
    assert out.startswith("Failed: ")
    assert "sb_secret_test" not in out


def test_a_failed_deletion_leaves_the_data(admin, session):
    with_data(session, TEST_ID)
    admin.deleted.return_value = Mock(ok=False, status_code=500)
    assert run("delete") == 1
    assert rows(session, Profile, TEST_ID) == 1


@pytest.mark.usefixtures("admin")
def test_the_result_goes_in_the_run_summary(monkeypatch, tmp_path):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    run("create", "--email", "new@fplsocial.dev")
    assert summary.read_text(encoding="utf-8") == "Created new@fplsocial.dev\n"


@pytest.mark.usefixtures("admin", "session")
def test_main_opens_a_session_on_the_engine():
    run("delete", "--email", "gone@fplsocial.dev")
    job.Session.assert_called_once_with(database.engine)
