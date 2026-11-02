from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class FixtureResponse(BaseModel):
    """A match, built from a fixtures row.

    event and kickoff_time are null while FPL hasn't scheduled a postponed match;
    scores are null until it's played. started is true from kickoff. FPL only sets
    finished once the gameweek's bonus points are confirmed, a day or more after
    the match, so use started to find matches still to be played.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    event: Optional[int] = None
    team_h: int
    team_a: int
    team_h_difficulty: int  # FPL's 1-5 rating
    team_a_difficulty: int
    kickoff_time: Optional[datetime] = None
    started: bool
    finished: bool
    team_h_score: Optional[int] = None
    team_a_score: Optional[int] = None
