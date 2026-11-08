from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict

# "mine": a team the user runs (they may run several). "following": anyone else's.
Relation = Literal["mine", "following"]


class TeamRequest(BaseModel):
    """The body of PUT /api/me/teams/{manager_id}."""

    relation: Relation


class UserTeamResponse(BaseModel):
    """An FPL team on the user's account, from user_teams and teams_tracked.

    name is the team's name (never the manager's), saved when a team is added, so
    the app needn't call /api/managers/{id} for every team. It's null for a team
    whose name hasn't been fetched yet (the hourly sync fills those in) or that FPL
    doesn't have.
    """

    model_config = ConfigDict(from_attributes=True)

    manager_id: int
    relation: Relation
    created_at: datetime
    name: Optional[str] = None
