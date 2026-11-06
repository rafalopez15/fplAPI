from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.models.profile import ProfileResponse
from src.services import profiles
from src.util.auth import CurrentUser
from src.util.database import get_session

# The signed-in user's own data. main.py sends Cache-Control: private, no-store on
# every response under /api/me, errors included, so the CDN never shares one.
me_router = APIRouter()


@me_router.get("/me")
def get_me(
    user_id: CurrentUser, session: Annotated[Session, Depends(get_session)]
) -> ProfileResponse:
    """Get the signed-in user's account, creating it on the first call.

    Needs an Authorization: Bearer header with a Supabase access token. Returns 401
    without a valid one, and 503 if sign-in isn't configured or is unavailable.
    """
    return profiles.get_profile(session, user_id)
