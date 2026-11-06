from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict

# "mine": a team the user runs (people often run several). "following": anyone else's.
Relation = Literal["mine", "following"]


class TeamRequest(BaseModel):
    """The body of PUT /api/me/teams/{manager_id}."""
    relation: Relation


class UserTeamResponse(BaseModel):
    """An FPL team on the user's account, built from a user_teams row.

    No team name: the app gets it from /api/managers/{id}, which the CDN caches.
    """
    model_config = ConfigDict(from_attributes=True)

    manager_id: int
    relation: Relation
    created_at: datetime
