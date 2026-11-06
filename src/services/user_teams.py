"""The FPL teams on a user's account: the ones they run and the ones they follow."""
from typing import List
from uuid import UUID
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from src.db.models import UserTeam
from src.models.user_team import Relation, UserTeamResponse
from src.services.profiles import ensure_profile
from src.util import fpl_client

# Bounds the FPL calls that following teams will cost once their activity is synced.
TEAM_LIMIT = 10


class TeamLimitError(Exception):
    """Raised when adding a team to an account that already has TEAM_LIMIT."""


def list_teams(session: Session, user_id: UUID) -> List[UserTeamResponse]:
    """The user's teams, newest first."""
    rows = session.scalars(
        select(UserTeam)
        .where(UserTeam.user_id == user_id)
        .order_by(UserTeam.created_at.desc(), UserTeam.manager_id)
    )
    return [UserTeamResponse.model_validate(row) for row in rows]


def save_team(
    session: Session, user_id: UUID, manager_id: int, relation: Relation
) -> UserTeamResponse:
    """Add a team to the user's account, or change its relation.

    Adding checks the team exists on FPL (one call), so it raises FplNotFoundError
    for an unknown id and FplUnavailableError if FPL is down. Changing an existing
    team doesn't call FPL. Raises TeamLimitError at TEAM_LIMIT teams.
    """
    if session.get(UserTeam, (user_id, manager_id)) is None:
        count = session.scalar(
            select(func.count()).select_from(UserTeam).where(UserTeam.user_id == user_id)
        )
        if count >= TEAM_LIMIT:
            raise TeamLimitError
        fpl_client.fetch_manager(manager_id)
        ensure_profile(session, user_id)
    # An upsert, so two requests adding the same team at once can't collide.
    row = session.scalars(
        insert(UserTeam)
        .values(user_id=user_id, manager_id=manager_id, relation=relation)
        .on_conflict_do_update(
            index_elements=[UserTeam.user_id, UserTeam.manager_id], set_={"relation": relation}
        )
        .returning(UserTeam),
        execution_options={"populate_existing": True},
    ).one()
    result = UserTeamResponse.model_validate(row)
    session.commit()
    return result


def remove_team(session: Session, user_id: UUID, manager_id: int) -> None:
    """Take a team off the user's account. Does nothing if it isn't there."""
    session.execute(
        delete(UserTeam).where(UserTeam.user_id == user_id, UserTeam.manager_id == manager_id)
    )
    session.commit()
