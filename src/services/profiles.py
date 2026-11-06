from uuid import UUID
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from src.db.models import Profile
from src.models.profile import ProfileResponse


def get_profile(session: Session, user_id: UUID) -> ProfileResponse:
    """The user's profile, created on their first call. Safe to call concurrently."""
    session.execute(insert(Profile).values(id=user_id).on_conflict_do_nothing())
    session.commit()
    return ProfileResponse.model_validate(session.get(Profile, user_id))
