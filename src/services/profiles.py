from uuid import UUID
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from src.db.models import DeletedAccount, Profile
from src.models.profile import ProfileResponse
from src.util import supabase_admin


class AccountDeletedError(Exception):
    """Raised when a deleted account tries to write: main.py turns it into a 401."""


def _lock_account(session: Session, user_id: UUID) -> None:
    """Take a per-account lock until the transaction ends.

    Without it, a write that started during a deletion could check deleted_accounts
    before the deletion commits, then recreate the profile right after.
    """
    session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(text(":user_id"), 0))),
        {"user_id": str(user_id)},
    )


def ensure_profile(session: Session, user_id: UUID) -> None:
    """Create the user's profile if it's missing. Safe to call concurrently.

    Call it before writing any account table: they reference profiles, and the app
    may save a team before it ever calls /api/me. Raises AccountDeletedError for a
    deleted account, whose token can still be valid for up to an hour.
    """
    _lock_account(session, user_id)
    if session.get(DeletedAccount, user_id) is not None:
        raise AccountDeletedError(user_id)
    session.execute(insert(Profile).values(id=user_id).on_conflict_do_nothing())


def get_profile(session: Session, user_id: UUID) -> ProfileResponse:
    """The user's profile, created on their first call."""
    ensure_profile(session, user_id)
    session.commit()
    return ProfileResponse.model_validate(session.get(Profile, user_id))


def delete_account(session: Session, user_id: UUID) -> None:
    """Delete the account: its profile, notes and teams, and its Supabase user.

    All or nothing. The rows are deleted, then Supabase is called, and only then is
    the transaction committed, so if Supabase fails nothing changes and a retry
    starts clean. This is the one place the API holds a transaction open across an
    HTTP call (supabase_admin.TIMEOUT bounds it): committing first could leave the
    person's email in Supabase. Raises SupabaseAdminError. Safe to retry: a user
    Supabase no longer has counts as deleted.
    """
    _lock_account(session, user_id)
    session.execute(
        insert(DeletedAccount).values(user_id=user_id).on_conflict_do_nothing()
    )
    session.execute(delete(Profile).where(Profile.id == user_id))  # cascades
    try:
        supabase_admin.delete_user(user_id)
    except supabase_admin.SupabaseAdminError:
        session.rollback()
        raise
    session.commit()
