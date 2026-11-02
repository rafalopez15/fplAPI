from typing import Optional
from pydantic import BaseModel, ConfigDict


class TeamResponse(BaseModel):
    """A Premier League team, built from a teams row."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: int
    name: str
    short_name: str

    # League table
    position: Optional[int] = None
    played: Optional[int] = None
    win: Optional[int] = None
    draw: Optional[int] = None
    loss: Optional[int] = None
    points: Optional[int] = None

    # FPL's strength ratings, used for fixture difficulty
    strength: Optional[int] = None
    strength_overall_home: Optional[int] = None
    strength_overall_away: Optional[int] = None
    strength_attack_home: Optional[int] = None
    strength_attack_away: Optional[int] = None
    strength_defence_home: Optional[int] = None
    strength_defence_away: Optional[int] = None
