"""The FPL teams on a user's account: the ones they run and the ones they follow."""

import math
from datetime import timedelta
from typing import List, Optional
from uuid import UUID
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from src.db.models import TrackedTeam, UserTeam
from src.models.user_team import Relation, UserTeamResponse
from src.services.profiles import ensure_profile
from src.util import fpl_client

# Both limits only stop scripts: a follow costs no FPL calls (design doc
# "Design: timeline, following and leagues").
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
    """The user's teams, newest first, with their names."""
    rows = session.execute(
        select(UserTeam, TrackedTeam.name)
        .outerjoin(TrackedTeam, TrackedTeam.manager_id == UserTeam.manager_id)
        .where(UserTeam.user_id == user_id)
        .order_by(UserTeam.created_at.desc(), UserTeam.manager_id)
    )
    return [to_response(row, name) for row, name in rows]


def to_response(row: UserTeam, name: Optional[str]) -> UserTeamResponse:
    return UserTeamResponse(
        manager_id=row.manager_id,
        relation=row.relation,
        created_at=row.created_at,
        name=name,
    )


def remember_team(session: Session, manager_id: int, name: Optional[str]) -> None:
    """Store or refresh a team's name in teams_tracked. Doesn't commit."""
    session.execute(
        insert(TrackedTeam)
        .values(manager_id=manager_id, name=name)
        .on_conflict_do_update(
            index_elements=[TrackedTeam.manager_id],
            set_={"name": name, "updated_at": func.now()},
        )
    )


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
        manager = fpl_client.fetch_manager(manager_id)
        ensure_profile(session, user_id)
        # Check again under the account lock ensure_profile took: parallel adds
        # all passed the first check. A double tap's team is already here.
        if session.get(UserTeam, (user_id, manager_id)) is None:
            check_limits(session, user_id)
        # The name comes free with the check; adding a team again refreshes it.
        remember_team(session, manager_id, manager.get("name"))
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
    result = to_response(
        row,
        session.scalar(
            select(TrackedTeam.name).where(TrackedTeam.manager_id == manager_id)
        ),
    )
    session.commit()
    return result


def check_limits(session: Session, user_id: UUID) -> None:
    """Raise TeamLimitError or TooManyAddsError if the account can't add a team."""
    count = session.scalar(
        select(func.count()).select_from(UserTeam).where(UserTeam.user_id == user_id)
    )
    if count >= TEAM_LIMIT:
        raise TeamLimitError
    # Removed teams don't count, so remove-and-re-add gets past this (FPL-44).
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
