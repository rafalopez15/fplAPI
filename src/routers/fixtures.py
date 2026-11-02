from typing import List, Optional
from fastapi import APIRouter
from src.models.fixture import FixtureResponse
from src.services import fixtures
from src.util.database import DataSession

fixtures_router = APIRouter()


@fixtures_router.get("/fixtures")
def get_fixtures(
    session: DataSession, finished: Optional[bool] = None, started: Optional[bool] = None
) -> List[FixtureResponse]:
    """List the season's fixtures, ordered by kickoff. Postponed fixtures without a
    kickoff time come last.

    Pass ?started=false for matches still to be played. FPL only marks a match
    finished once the gameweek's bonus points are confirmed, so ?finished=false
    also returns matches played in the last day or so.
    """
    return fixtures.get_fixtures(session, finished, started)
