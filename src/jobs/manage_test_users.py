"""Create, delete or clear test users on staging (FPL-85). GitHub Actions runs it by
hand: the Staging test users workflow.

    python -m src.jobs.manage_test_users create [--email test@fplsocial.dev]
    python -m src.jobs.manage_test_users delete [--email test@fplsocial.dev]
    python -m src.jobs.manage_test_users clear --confirm CLEAR

Needs SUPABASE_URL, SUPABASE_SECRET_KEY and DATABASE_URL for staging, and
TEST_USER_PASSWORD for create. Refuses to run against any other project, and only
ever touches emails in TEST_DOMAIN. Deleting goes through delete_account(), as
DELETE /api/me does, so the user's teams and notes go too.
"""

import argparse
import logging
import os
import sys
from typing import Iterator, Optional
from uuid import UUID
import requests
from sqlalchemy.orm import Session
from src.services import profiles
from src.util import database
from src.util.config import DATABASE_URL, SUPABASE_SECRET_KEY, SUPABASE_URL
from src.util.supabase_admin import SupabaseAdminError

logger = logging.getLogger(__name__)

STAGING_REF = "ltasgegihkapmdqlkaov"  # fpl-api-staging
TEST_DOMAIN = "@fplsocial.dev"
DEFAULT_EMAIL = "test@fplsocial.dev"
TIMEOUT = 10
PAGE_SIZE = 200


class RefusedError(Exception):
    """Raised when a guard refuses to run. Nothing has been changed."""


def check_staging(supabase_url: Optional[str], database_url: str) -> None:
    """Refuse unless both the Auth project and the database are staging's."""
    if supabase_url != f"https://{STAGING_REF}.supabase.co":
        raise RefusedError("SUPABASE_URL isn't staging's project")
    # Supabase's pooler user is postgres.<ref>, and the direct host db.<ref>.
    if STAGING_REF not in database_url:
        raise RefusedError("DATABASE_URL isn't staging's database")


def check_test_email(email: str) -> str:
    email = email.strip().lower()
    if not email.endswith(TEST_DOMAIN) or email == TEST_DOMAIN:
        raise RefusedError(f"Only {TEST_DOMAIN} emails are test users")
    return email


def admin(method: str, path: str, **kwargs) -> dict:
    """Call Supabase's Auth Admin API. Raises SupabaseAdminError with the status only,
    never the key or the body."""
    try:
        response = requests.request(
            method,
            f"{SUPABASE_URL}/auth/v1/admin/{path}",
            headers={
                "apikey": SUPABASE_SECRET_KEY,
                "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
            },
            timeout=TIMEOUT,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise SupabaseAdminError(
            f"Supabase couldn't be reached: {type(exc).__name__}"
        ) from exc
    if not response.ok:
        raise SupabaseAdminError(f"Supabase answered {response.status_code}")
    return response.json()


def all_users() -> Iterator[dict]:
    """Every user in the project, page by page until an empty page (Supabase may
    send fewer than PAGE_SIZE before the end)."""
    page = 1
    while True:
        params = {"page": page, "per_page": PAGE_SIZE}
        users = admin("GET", "users", params=params).get("users") or []
        if not users:
            return
        yield from users
        page += 1


def find_user(email: str) -> Optional[dict]:
    return next(
        (u for u in all_users() if (u.get("email") or "").lower() == email), None
    )


def create(email: str, password: Optional[str]) -> str:
    """Create a confirmed test user, or reset an existing one's password. Safe to run
    again. Returns what happened."""
    if not password:
        raise RefusedError("TEST_USER_PASSWORD isn't set")
    body = {"password": password, "email_confirm": True}
    user = find_user(email)
    if user:
        admin("PUT", f"users/{user['id']}", json=body)
        return f"Reset the password of {email}"
    admin("POST", "users", json={"email": email, **body})
    return f"Created {email}"


def delete(session: Session, email: str) -> str:
    user = find_user(email)
    if user is None:
        return f"No user {email}"
    profiles.delete_account(session, UUID(user["id"]))
    return f"Deleted {email}"


def clear(session: Session, confirm: str) -> str:
    """Delete every test user. Only TEST_DOMAIN emails are ever matched."""
    if confirm != "CLEAR":
        raise RefusedError("clear needs --confirm CLEAR")
    emails = []
    # Listed first, so deleting doesn't shift the pages being read.
    for user in list(all_users()):
        email = (user.get("email") or "").lower()
        if email.endswith(TEST_DOMAIN):
            profiles.delete_account(session, UUID(user["id"]))
            emails.append(email)
    return f"Cleared {len(emails)} test user(s)" + "".join(
        f"\n- {e}" for e in sorted(emails)
    )


def report(message: str) -> None:
    """Print, and add to the run's summary in GitHub Actions."""
    print(message)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as file:
            file.write(message + "\n")


def main(argv: Optional[list] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Manage staging's test users.")
    parser.add_argument("action", choices=["create", "delete", "clear"])
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    try:
        check_staging(SUPABASE_URL, DATABASE_URL)
        if args.action == "create":
            message = create(
                check_test_email(args.email), os.getenv("TEST_USER_PASSWORD")
            )
        else:
            with Session(database.engine) as session:
                if args.action == "delete":
                    message = delete(session, check_test_email(args.email))
                else:
                    message = clear(session, args.confirm)
    except RefusedError as exc:
        report(f"Refused: {exc}")
        return 2
    except SupabaseAdminError as exc:
        report(f"Failed: {exc}")
        return 1
    report(message)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
