from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.db.models import Team
from src.models.team import TeamResponse

# Each club's home kit colors (primary, secondary), keyed by FPL's team code.
# The code stays the same for a club every season; FPL's team id doesn't. FPL has
# no colors, so this is kept by hand: traditional home colors, recognisable rather
# than exact. Add promoted clubs each summer. Clubs missing here get null colors.
KIT_COLORS = {
    3: ("#EF0107", "#FFFFFF"),   # Arsenal
    7: ("#670E36", "#95BFE5"),   # Aston Villa
    91: ("#DA291C", "#000000"),  # Bournemouth
    94: ("#E30613", "#FFFFFF"),  # Brentford
    36: ("#0057B8", "#FFFFFF"),  # Brighton
    8: ("#034694", "#FFFFFF"),   # Chelsea
    9: ("#59CBE8", "#FFFFFF"),   # Coventry City
    31: ("#1B458F", "#C4122E"),  # Crystal Palace
    11: ("#003399", "#FFFFFF"),  # Everton
    54: ("#FFFFFF", "#000000"),  # Fulham
    88: ("#F5A12D", "#000000"),  # Hull City
    40: ("#0044A9", "#FFFFFF"),  # Ipswich Town
    2: ("#FFFFFF", "#1D428A"),   # Leeds
    14: ("#C8102E", "#FFFFFF"),  # Liverpool
    43: ("#6CABDD", "#FFFFFF"),  # Man City
    1: ("#DA291C", "#FFFFFF"),   # Man Utd
    4: ("#000000", "#FFFFFF"),   # Newcastle
    17: ("#DD0000", "#FFFFFF"),  # Nott'm Forest
    6: ("#FFFFFF", "#132257"),   # Spurs
    56: ("#EB172B", "#FFFFFF"),  # Sunderland
}


def _to_response(row: Team) -> TeamResponse:
    """Build the response from a teams row, adding the club's kit colors."""
    primary, secondary = KIT_COLORS.get(row.code, (None, None))
    return TeamResponse.model_validate(row).model_copy(
        update={"primary_color": primary, "secondary_color": secondary}
    )


def get_teams(session: Session) -> List[TeamResponse]:
    """Return all Premier League teams, in FPL id order."""
    rows = session.scalars(select(Team).order_by(Team.id))
    return [_to_response(row) for row in rows]


def get_team_by_name(session: Session, name: str) -> Optional[TeamResponse]:
    """Return the team whose name matches exactly, or None.

    Matching is case-sensitive and uses FPL's names, such as "Man City" rather
    than "Manchester City".
    """
    row = session.scalars(select(Team).where(Team.name == name)).first()
    return _to_response(row) if row else None
