"""What each team in a classic league did in a gameweek, as the gameweek pass stored
it. The first request for a league starts tracking it, after one call to FPL to
check it exists and is small enough."""

from datetime import timedelta
from typing import Optional
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from src.db.models import (
    Event,
    LeagueTeam,
    TeamGameweek,
    TrackedLeague,
    TrackedTeam,
)
from src.models.league import (
    LeagueActivityResponse,
    LeagueStandingsResponse,
    TeamActivity,
)
from src.services import leagues
from src.services.user_teams import remember_team

# Each tracked league costs FPL calls every gameweek, so public requests can only
# start so many.
LEAGUE_LIMIT = 200
NEW_LEAGUE_LIMIT = 20  # per NEW_LEAGUE_WINDOW
NEW_LEAGUE_WINDOW = timedelta(hours=1)
# No exact wait exists for the total cap, so both answers use the window.
RETRY_AFTER = 3600
# A league nobody has asked about for this long stops being tracked.
MAX_IDLE = timedelta(days=14)


class EventNotFoundError(Exception):
    """No such gameweek."""


class DeadlineNotPassedError(Exception):
    """The gameweek's deadline hasn't passed, so FPL has no picks for it yet."""


class LeagueTooBigError(Exception):
    """The league has more than one page of teams."""


class TooManyLeaguesError(Exception):
    """Tracking another league would pass LEAGUE_LIMIT or NEW_LEAGUE_LIMIT."""


def latest_event(session: Session) -> Optional[int]:
    """The latest gameweek whose deadline has passed, or None before the first."""
    return session.scalar(
        select(func.max(Event.id)).where(Event.deadline_time <= func.now())
    )


def resolve_event(session: Session, event: Optional[int]) -> int:
    """The gameweek asked for, or the latest whose deadline has passed.

    Raises EventNotFoundError for an unknown gameweek (or none passed yet) and
    DeadlineNotPassedError for one still to come.
    """
    if event is None:
        latest = latest_event(session)
        if latest is None:
            raise DeadlineNotPassedError
        return latest
    deadline_passed = session.scalar(
        select(Event.deadline_time <= func.now()).where(Event.id == event)
    )
    if deadline_passed is None:
        raise EventNotFoundError
    if not deadline_passed:
        raise DeadlineNotPassedError
    return event


def check_limits(session: Session) -> None:
    """Raise TooManyLeaguesError if no new league can be tracked now."""
    total, recent = session.execute(
        select(
            func.count(),
            func.count().filter(
                TrackedLeague.created_at > func.now() - NEW_LEAGUE_WINDOW
            ),
        ).select_from(TrackedLeague)
    ).one()
    if total >= LEAGUE_LIMIT or recent >= NEW_LEAGUE_LIMIT:
        raise TooManyLeaguesError


def track(session: Session, league_id: int) -> None:
    """Mark the league as requested now, tracking it if it isn't yet. Commits.

    A new league is checked with FPL first: FplNotFoundError if it doesn't exist
    (or is head-to-head), FplUnavailableError if FPL is down, LeagueTooBigError past
    one page of teams, TooManyLeaguesError past the limits.
    """
    if session.get(TrackedLeague, league_id) is None:
        check_limits(session)
        # Don't hold a pooler connection while FPL answers.
        session.commit()
        standings = leagues.get_standings(league_id)
        if standings.has_next or standings.new_entries_has_next:
            raise LeagueTooBigError
    session.execute(
        insert(TrackedLeague)
        .values(league_id=league_id)
        .on_conflict_do_update(
            index_elements=[TrackedLeague.league_id],
            set_={"last_requested_at": func.now()},
        )
    )
    session.commit()


def purge(session: Session) -> int:
    """Stop tracking leagues not requested for MAX_IDLE. Returns how many. Their
    teams' stored gameweeks stay. Doesn't commit."""
    return len(
        session.scalars(
            delete(TrackedLeague)
            .where(TrackedLeague.last_requested_at < func.now() - MAX_IDLE)
            .returning(TrackedLeague.league_id)
        ).all()
    )


def save_teams(session: Session, league_id: int, standings: LeagueStandingsResponse):
    """Replace the league's teams with its standings' first page and new entries,
    and store their names. Doesn't commit."""
    teams = {row.entry: row.entry_name for row in standings.standings}
    teams.update((row.entry, row.entry_name) for row in standings.new_entries)
    session.execute(
        delete(LeagueTeam).where(
            LeagueTeam.league_id == league_id, LeagueTeam.manager_id.not_in(teams)
        )
    )
    for manager_id, name in teams.items():
        remember_team(session, manager_id, name)
    if teams:
        session.execute(
            insert(LeagueTeam)
            .values([{"league_id": league_id, "manager_id": m} for m in teams])
            .on_conflict_do_nothing()
        )
    session.execute(
        update(TrackedLeague)
        .where(TrackedLeague.league_id == league_id)
        .values(teams_updated_at=func.now())
    )


def get_activity(
    session: Session, league_id: int, event: int
) -> LeagueActivityResponse:
    """What's stored for the league's teams in the gameweek, by team id."""
    teams_updated_at = session.scalar(
        select(TrackedLeague.teams_updated_at).where(
            TrackedLeague.league_id == league_id
        )
    )
    rows = session.execute(
        select(LeagueTeam.manager_id, TrackedTeam, TeamGameweek)
        .outerjoin(TrackedTeam, TrackedTeam.manager_id == LeagueTeam.manager_id)
        .outerjoin(
            TeamGameweek,
            and_(
                TeamGameweek.manager_id == LeagueTeam.manager_id,
                TeamGameweek.event == event,
            ),
        )
        .where(LeagueTeam.league_id == league_id)
        .order_by(LeagueTeam.manager_id)
    ).all()
    pending = teams_updated_at is None or any(
        team is None or team.last_event is None or team.last_event < event
        for _, team, _ in rows
    )
    return LeagueActivityResponse(
        league_id=league_id,
        event=event,
        pending=pending,
        teams=[
            TeamActivity(
                entry=manager_id,
                entry_name=team.name if team else None,
                event=event,
                transfers=gameweek.transfers,
                transfers_cost=gameweek.transfers_cost,
                chip=gameweek.chip,
                captain=gameweek.captain,
                vice_captain=gameweek.vice_captain,
                captain_changed=gameweek.captain_changed,
                points=gameweek.points,
            )
            for manager_id, team, gameweek in rows
            if gameweek is not None
        ],
    )
