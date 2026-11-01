from fastapi import APIRouter, HTTPException
from src.services import teams

teams_router = APIRouter()


@teams_router.get("/teams")
async def get_teams():
    """List all Premier League teams."""
    return teams.get_teams()


@teams_router.get("/teams/{team_name}")
async def get_team_by_name(team_name: str):
    """Get one team by its exact FPL name, such as "Arsenal" or "Man City".

    Matching is case-sensitive. Returns 404 if no team has that name.
    """
    result = teams.get_team_by_name(team_name)
    if not result:
        raise HTTPException(status_code=404, detail="Team not found")

    return result
