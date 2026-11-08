"""The FPL teams on a user's account: the ones they run and the ones they follow."""

import math
from datetime import timedelta
from typing import List
from uuid import UUID
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from src.db.models import UserTeam
from src.models.user_team import Relation, UserTeamResponse
from src.services.profiles import ensure_profile
from src.util import fpl_client

# Not a product limit: following costs nothing, since the timeline fetches each
# distinct team once per gameweek however many accounts follow it (design doc:
# "Design: timeline, following and leagues"). Both limits only stop scripts.
TEAM_LIMIT = 1000
ADD_LIMIT = 60  # new teams per account per ADD_WINDOW
ADD_WINDOW = timedelta(hours=1)


class TeamLimitError(Exception):
    """Raised when adding a team to an account that already has TEAM_LIMIT."""


class TooManyAddsError(Exception):
    """Raised when an account has added ADD_LIMIT teams within ADD_WINDOW.

    retry_after is the seconds until the oldest of those adds leaves the window.
    """

    def __init__(self, retry_after: int):
        super().__init__(retry_after)
        self.retry_after = retry_after


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
    """Add a team to the account, or switch its relation.

    Adding calls FPL once to check the team exists: FplNotFoundError if it doesn't,
    FplUnavailableError if FPL is down. Switching doesn't call FPL. Adding raises
    TeamLimitError past TEAM_LIMIT, and TooManyAddsError past ADD_LIMIT within
    ADD_WINDOW; switching counts toward neither.
    """
    if session.get(UserTeam, (user_id, manager_id)) is None:
        check_limits(session, user_id)
        # Don't hold a pooler connection while FPL answers (up to 5s). Nothing's
        # written yet, so this only ends the read transaction.
        session.commit()
        fpl_client.fetch_manager(manager_id)
        ensure_profile(session, user_id)
        # Again, now that ensure_profile holds the account's lock until commit:
        # adds sent in parallel all passed the first check during the FPL call.
        # Skipped if a double tap added this team meanwhile; that's a switch.
        if session.get(UserTeam, (user_id, manager_id)) is None:
            check_limits(session, user_id)
    # Upsert, so a double tap can't hit a duplicate key.
    row = session.scalars(
        insert(UserTeam)
        .values(user_id=user_id, manager_id=manager_id, relation=relation)
        .on_conflict_do_update(
            index_elements=[UserTeam.user_id, UserTeam.manager_id],
            set_={"relation": relation},
        )
        .returning(UserTeam),
        execution_options={"populate_existing": True},
    ).one()
    result = UserTeamResponse.model_validate(row)
    session.commit()
    return result


def check_limits(session: Session, user_id: UUID) -> None:
    """Raise TeamLimitError or TooManyAddsError if the account can't add a team."""
    count = session.scalar(
        select(func.count()).select_from(UserTeam).where(UserTeam.user_id == user_id)
    )
    if count >= TEAM_LIMIT:
        raise TeamLimitError
    # Counted from created_at, so a team removed since doesn't count. Removing and
    # re-adding can get past it, which costs FPL no more than the public routes do.
    recent, oldest, now = session.execute(
        select(func.count(), func.min(UserTeam.created_at), func.now()).where(
            UserTeam.user_id == user_id,
            UserTeam.created_at > func.now() - ADD_WINDOW,
        )
    ).one()
    if recent >= ADD_LIMIT:
        wait = (oldest + ADD_WINDOW - now).total_seconds()
        raise TooManyAddsError(max(1, math.ceil(wait)))


def remove_team(session: Session, user_id: UUID, manager_id: int) -> None:
    """Remove a team from the account, if it's there."""
    session.execute(
        delete(UserTeam).where(
            UserTeam.user_id == user_id, UserTeam.manager_id == manager_id
        )
    )
    session.commit()
