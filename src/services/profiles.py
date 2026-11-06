from uuid import UUID
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from src.db.models import Profile
from src.models.profile import ProfileResponse


def ensure_profile(session: Session, user_id: UUID) -> None:
    """Create the user's profile if it's missing. Safe to call concurrently.

    Call it before writing any account table: they reference profiles, and the app
    may save a team before it ever calls /api/me.
    """
    session.execute(insert(Profile).values(id=user_id).on_conflict_do_nothing())


def get_profile(session: Session, user_id: UUID) -> ProfileResponse:
    """The user's profile, created on their first call."""
    ensure_profile(session, user_id)
    session.commit()
    return ProfileResponse.model_validate(session.get(Profile, user_id))
