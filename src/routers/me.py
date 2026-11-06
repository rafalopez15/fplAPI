from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.models.profile import ProfileResponse
from src.models.user_team import TeamRequest, UserTeamResponse
from src.routers.managers import ManagerId, manager_not_found
from src.services import profiles, user_teams
from src.util.auth import CurrentUser
from src.util.database import get_session
from src.util.fpl_client import FplNotFoundError

# The signed-in user's own data. main.py sends Cache-Control: private, no-store on
# every response under /api/me, errors included, so the CDN never shares one.
# Each route needs an Authorization: Bearer header with a Supabase access token:
# 401 without a valid one, 503 if sign-in isn't configured or is unavailable.
me_router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]


@me_router.get("/me")
def get_me(user_id: CurrentUser, session: SessionDep) -> ProfileResponse:
    """Get the signed-in user's account, creating it on the first call."""
    return profiles.get_profile(session, user_id)


@me_router.get("/me/teams")
def get_my_teams(user_id: CurrentUser, session: SessionDep) -> List[UserTeamResponse]:
    """List the FPL teams on the user's account, newest first: theirs and followed."""
    return user_teams.list_teams(session, user_id)


@me_router.put("/me/teams/{manager_id}")
def put_my_team(
    manager_id: ManagerId, body: TeamRequest, user_id: CurrentUser, session: SessionDep
) -> UserTeamResponse:
    """Add an FPL team to the account as "mine" or "following", or switch it.

    Adding checks the team exists on FPL: 404 if it doesn't, 503 if FPL can't be
    reached. 409 once the account has 10 teams.
    """
    try:
        return user_teams.save_team(session, user_id, manager_id, body.relation)
    except FplNotFoundError as exc:
        raise manager_not_found() from exc
    except user_teams.TeamLimitError as exc:
        raise HTTPException(status_code=409, detail="Team limit reached") from exc


@me_router.delete("/me/teams/{manager_id}", status_code=204)
def delete_my_team(manager_id: ManagerId, user_id: CurrentUser, session: SessionDep) -> None:
    """Take an FPL team off the account. 204 even if it wasn't there."""
    user_teams.remove_team(session, user_id, manager_id)
