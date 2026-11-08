from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.models.profile import ProfileResponse
from src.models.user_team import TeamRequest, UserTeamResponse
from src.routers.managers import manager_not_found
from src.routers.params import ManagerId
from src.services import profiles, user_teams
from src.util.auth import CurrentUser
from src.util.database import get_session
from src.util.fpl_client import FplNotFoundError
from src.util.supabase_admin import SupabaseAdminError

# The signed-in user's own data. Every route needs a Supabase access token
# (Authorization: Bearer): 401 without a valid one, 503 if sign-in is unavailable.
# main.py marks every response under /api/me private, no-store.
me_router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]


@me_router.get("/me")
def get_me(user_id: CurrentUser, session: SessionDep) -> ProfileResponse:
    """Get the signed-in user's account, creating it on the first call."""
    return profiles.get_profile(session, user_id)


@me_router.delete("/me", status_code=204)
def delete_me(user_id: CurrentUser, session: SessionDep) -> None:
    """Delete the account: its notes, its teams and its sign-in. FPL teams aren't
    touched.

    All or nothing: 503 if it can't be done right now, with nothing changed, so it's
    safe to retry. After a 204, the account's token is refused for writes.
    """
    try:
        profiles.delete_account(session, user_id)
    except SupabaseAdminError as exc:
        raise HTTPException(
            status_code=503, detail="Couldn't delete your account right now"
        ) from exc


@me_router.get("/me/teams")
def get_my_teams(user_id: CurrentUser, session: SessionDep) -> List[UserTeamResponse]:
    """List the account's FPL teams, newest first."""
    return user_teams.list_teams(session, user_id)


@me_router.put("/me/teams/{manager_id}")
def put_my_team(
    manager_id: ManagerId, body: TeamRequest, user_id: CurrentUser, session: SessionDep
) -> UserTeamResponse:
    """Add a team as "mine" or "following", or switch it.

    Adding checks FPL: 404 for an unknown team, 503 if FPL is down. 409 at 1,000
    teams, and 429 after 60 new teams in an hour.
    """
    try:
        return user_teams.save_team(session, user_id, manager_id, body.relation)
    except FplNotFoundError as exc:
        raise manager_not_found() from exc
    except user_teams.TeamLimitError as exc:
        raise HTTPException(status_code=409, detail="Team limit reached") from exc
    except user_teams.TooManyAddsError as exc:
        raise HTTPException(
            status_code=429,
            detail="Too many follows, try again later",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc


@me_router.delete("/me/teams/{manager_id}", status_code=204)
def delete_my_team(
    manager_id: ManagerId, user_id: CurrentUser, session: SessionDep
) -> None:
    """Remove a team from the account. 204 even if it wasn't there."""
    user_teams.remove_team(session, user_id, manager_id)
