from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.db.models import Team
from src.models.team import TeamResponse


def get_teams(session: Session) -> List[TeamResponse]:
    """Return all Premier League teams, in FPL id order."""
    rows = session.scalars(select(Team).order_by(Team.id))
    return [TeamResponse.model_validate(row) for row in rows]


def get_team_by_name(session: Session, name: str) -> Optional[TeamResponse]:
    """Return the team whose name matches exactly, or None.

    Matching is case-sensitive and uses FPL's names, such as "Man City" rather
    than "Manchester City".
    """
    row = session.scalars(select(Team).where(Team.name == name)).first()
    return TeamResponse.model_validate(row) if row else None
