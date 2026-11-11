from fastapi import APIRouter
from src.routers.events import events_router
from src.routers.teams import teams_router
from src.routers.elements import elements_router
from src.routers.fixtures import fixtures_router
from src.routers.leagues import leagues_router
from src.routers.managers import managers_router
from src.routers.me import me_router
from src.routers.notes import notes_router

routers = APIRouter()
routers.include_router(events_router)
routers.include_router(teams_router)
routers.include_router(elements_router)
routers.include_router(fixtures_router)
routers.include_router(managers_router)
routers.include_router(leagues_router)
routers.include_router(me_router)
routers.include_router(notes_router)
