"""What teams did each gameweek, stored by the gameweek pass: one team_gameweeks row
per team and gameweek, and teams_tracked.last_event to show how far it got."""

from typing import Optional
from sqlalchemy import Row, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from src.db.models import LeagueTeam, TeamGameweek, TrackedTeam


def build(
    manager_id: int,
    event: int,
    picks: dict,
    transfers: list[dict],
    previous_captain: Optional[int],
) -> dict:
    """A team_gameweeks row from FPL's picks for the gameweek and its real transfers.

    previous_captain is the captain of the team's last stored gameweek, None if it
    has none, which leaves captain_changed null.
    """
    chosen = picks.get("picks") or []
    captain = next((p["element"] for p in chosen if p.get("is_captain")), None)
    vice = next((p["element"] for p in chosen if p.get("is_vice_captain")), None)
    history = picks.get("entry_history") or {}
    return {
        "manager_id": manager_id,
        "event": event,
        "transfers": transfers,
        "transfers_cost": history.get("event_transfers_cost") or 0,
        "chip": picks.get("active_chip"),
        "captain": captain,
        "vice_captain": vice,
        "captain_changed": (
            None if previous_captain is None else captain != previous_captain
        ),
    }


def teams_behind(session: Session, latest: int) -> list[Row]:
    """(manager_id, last_event) for each tracked league's team that the pass hasn't
    taken up to the latest gameweek, by team id."""
    return session.execute(
        select(TrackedTeam.manager_id, TrackedTeam.last_event)
        .where(
            TrackedTeam.manager_id.in_(select(LeagueTeam.manager_id)),
            or_(TrackedTeam.last_event.is_(None), TrackedTeam.last_event < latest),
        )
        .order_by(TrackedTeam.manager_id)
    ).all()


def last_captain(session: Session, manager_id: int, before: int) -> Optional[int]:
    """The captain in the team's latest stored gameweek before this one, or None if
    none is."""
    return session.scalar(
        select(TeamGameweek.captain)
        .where(TeamGameweek.manager_id == manager_id, TeamGameweek.event < before)
        .order_by(TeamGameweek.event.desc())
        .limit(1)
    )


def save(session: Session, manager_id: int, rows: list[dict], last_event: int) -> None:
    """Store the team's new gameweeks and how far the pass got. Doesn't commit."""
    if rows:
        statement = insert(TeamGameweek).values(rows)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[TeamGameweek.manager_id, TeamGameweek.event],
                set_={
                    name: statement.excluded[name]
                    for name in rows[0]
                    if name not in ("manager_id", "event")
                },
            )
        )
    session.execute(
        update(TrackedTeam)
        .where(TrackedTeam.manager_id == manager_id)
        .values(last_event=last_event)
    )
