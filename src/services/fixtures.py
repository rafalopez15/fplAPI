from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.db.models import Fixture
from src.models.fixture import FixtureResponse


def get_fixtures(
    session: Session, finished: Optional[bool] = None, started: Optional[bool] = None
) -> List[FixtureResponse]:
    """Return fixtures ordered by kickoff, unscheduled ones last, then by id.

    Each filter applies only when it isn't None. started=False gives the matches
    still to be played; finished=False also includes played matches whose bonus
    points FPL hasn't confirmed yet.
    """
    query = select(Fixture).order_by(Fixture.kickoff_time.asc().nulls_last(), Fixture.id)
    if finished is not None:
        query = query.where(Fixture.finished == finished)
    if started is not None:
        query = query.where(Fixture.started == started)
    return [FixtureResponse.model_validate(row) for row in session.scalars(query)]
