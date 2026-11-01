from fastapi import APIRouter, HTTPException
from src.services import teams

teams_router = APIRouter()


@teams_router.get("/teams")
async def get_teams():
    return teams.get_teams()


@teams_router.get("/teams/{team_name}")
async def get_team_by_name(team_name: str):
    result = teams.get_team_by_name(team_name)
    if not result:
        raise HTTPException(status_code=404, detail="Team not found")

    return result
