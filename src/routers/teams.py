from typing import List
from fastapi import APIRouter, HTTPException
from src.models.team import TeamResponse
from src.services import teams
from src.util.database import DataSession

teams_router = APIRouter()


@teams_router.get("/teams")
def get_teams(session: DataSession) -> List[TeamResponse]:
    """List all Premier League teams."""
    return teams.get_teams(session)


@teams_router.get("/teams/{team_name}")
def get_team_by_name(session: DataSession, team_name: str) -> TeamResponse:
    """Get one team by its exact FPL name, such as "Arsenal" or "Man City".

    Matching is case-sensitive. Returns 404 if no team has that name.
    """
    result = teams.get_team_by_name(session, team_name)
    if not result:
        raise HTTPException(status_code=404, detail="Team not found")

    return result
