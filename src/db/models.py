"""SQLAlchemy tables for the FPL data, synced from FPL by the jobs and read by the API.

Column names match FPL's field names, so rows map 1:1 onto the Pydantic response
models. Ids are FPL's own, never generated here. Tables are only upserted, never
deleted from, so players FPL drops stay for their history rows.
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from sqlalchemy import DateTime, ForeignKey, Identity, MetaData, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names, so Alembic migrations can refer to them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        Decimal: Numeric,
    }


def fpl_id() -> Mapped[int]:
    """A primary key holding FPL's id, so Postgres must not generate one."""
    return mapped_column(primary_key=True, autoincrement=False)


def updated_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = fpl_id()
    code: Mapped[int]
    name: Mapped[str]
    short_name: Mapped[str]
    position: Mapped[Optional[int]]
    played: Mapped[Optional[int]]
    win: Mapped[Optional[int]]
    draw: Mapped[Optional[int]]
    loss: Mapped[Optional[int]]
    points: Mapped[Optional[int]]
    strength: Mapped[Optional[int]]
    strength_overall_home: Mapped[Optional[int]]
    strength_overall_away: Mapped[Optional[int]]
    strength_attack_home: Mapped[Optional[int]]
    strength_attack_away: Mapped[Optional[int]]
    strength_defence_home: Mapped[Optional[int]]
    strength_defence_away: Mapped[Optional[int]]
    updated_at: Mapped[datetime] = updated_at()


class ElementType(Base):
    """A position: 1 goalkeeper, 2 defender, 3 midfielder, 4 forward."""
    __tablename__ = "element_types"

    id: Mapped[int] = fpl_id()
    singular_name: Mapped[str]
    singular_name_short: Mapped[str]
    plural_name: Mapped[str]
    plural_name_short: Mapped[str]
    squad_select: Mapped[Optional[int]]
    squad_min_play: Mapped[Optional[int]]
    squad_max_play: Mapped[Optional[int]]
    element_count: Mapped[Optional[int]]
    updated_at: Mapped[datetime] = updated_at()


class Element(Base):
    """A player. Columns match ElementResponse, including which ones are required."""
    __tablename__ = "elements"

    # Required
    id: Mapped[int] = fpl_id()
    web_name: Mapped[str]
    team: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    element_type: Mapped[int] = mapped_column(ForeignKey("element_types.id"))
    now_cost: Mapped[int]  # in tenths of a million: 62 is £6.2m
    status: Mapped[str]

    # Identity
    code: Mapped[Optional[int]]
    first_name: Mapped[Optional[str]]
    second_name: Mapped[Optional[str]]
    team_code: Mapped[Optional[int]]
    photo: Mapped[Optional[str]]

    # Availability
    news: Mapped[Optional[str]]
    news_added: Mapped[Optional[datetime]]
    chance_of_playing_next_round: Mapped[Optional[int]]
    chance_of_playing_this_round: Mapped[Optional[int]]
    can_select: Mapped[Optional[bool]]
    can_transact: Mapped[Optional[bool]]
    removed: Mapped[Optional[bool]]

    # Price changes and transfers
    cost_change_event: Mapped[Optional[int]]
    cost_change_start: Mapped[Optional[int]]
    selected_by_percent: Mapped[Optional[Decimal]]
    transfers_in_event: Mapped[Optional[int]]
    transfers_out_event: Mapped[Optional[int]]

    # Points
    total_points: Mapped[Optional[int]]
    event_points: Mapped[Optional[int]]
    points_per_game: Mapped[Optional[Decimal]]
    form: Mapped[Optional[Decimal]]
    ep_next: Mapped[Optional[Decimal]]

    # Season stats
    minutes: Mapped[Optional[int]]
    starts: Mapped[Optional[int]]
    goals_scored: Mapped[Optional[int]]
    assists: Mapped[Optional[int]]
    clean_sheets: Mapped[Optional[int]]
    goals_conceded: Mapped[Optional[int]]
    saves: Mapped[Optional[int]]
    bonus: Mapped[Optional[int]]
    yellow_cards: Mapped[Optional[int]]
    red_cards: Mapped[Optional[int]]

    # Advanced stats
    expected_goals: Mapped[Optional[Decimal]]
    expected_assists: Mapped[Optional[Decimal]]
    expected_goal_involvements: Mapped[Optional[Decimal]]
    expected_goals_conceded: Mapped[Optional[Decimal]]
    ict_index: Mapped[Optional[Decimal]]

    updated_at: Mapped[datetime] = updated_at()


class Event(Base):
    """A gameweek. The stats are null for gameweeks that haven't been played.

    most_selected, top_element and the other player ids have no foreign key, so a
    player missing from elements can't fail a whole sync.
    """
    __tablename__ = "events"

    id: Mapped[int] = fpl_id()
    name: Mapped[str]
    deadline_time: Mapped[datetime]
    deadline_time_epoch: Mapped[int]
    deadline_time_game_offset: Mapped[Optional[int]]
    release_time: Mapped[Optional[datetime]]
    finished: Mapped[bool]
    data_checked: Mapped[bool]
    is_previous: Mapped[bool]
    is_current: Mapped[bool]
    is_next: Mapped[bool]
    average_entry_score: Mapped[Optional[int]]
    highest_score: Mapped[Optional[int]]
    highest_scoring_entry: Mapped[Optional[int]]
    transfers_made: Mapped[Optional[int]]
    most_selected: Mapped[Optional[int]]
    most_transferred_in: Mapped[Optional[int]]
    most_captained: Mapped[Optional[int]]
    most_vice_captained: Mapped[Optional[int]]
    top_element: Mapped[Optional[int]]
    top_element_points: Mapped[Optional[int]]  # from FPL's top_element_info
    chip_plays: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = updated_at()


class PlayerFixtureHistory(Base):
    """One player's stats in one fixture, from /element-summary/{id}/.

    Double gameweeks have two rows for the same round; blank gameweeks have none.
    """
    __tablename__ = "player_fixture_history"

    element: Mapped[int] = mapped_column(ForeignKey("elements.id"), primary_key=True)
    fixture: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    round: Mapped[int] = mapped_column(index=True)
    opponent_team: Mapped[Optional[int]]
    was_home: Mapped[Optional[bool]]
    kickoff_time: Mapped[Optional[datetime]]
    team_h_score: Mapped[Optional[int]]
    team_a_score: Mapped[Optional[int]]
    minutes: Mapped[Optional[int]]
    total_points: Mapped[Optional[int]]
    goals_scored: Mapped[Optional[int]]
    assists: Mapped[Optional[int]]
    clean_sheets: Mapped[Optional[int]]
    goals_conceded: Mapped[Optional[int]]
    own_goals: Mapped[Optional[int]]
    penalties_saved: Mapped[Optional[int]]
    penalties_missed: Mapped[Optional[int]]
    yellow_cards: Mapped[Optional[int]]
    red_cards: Mapped[Optional[int]]
    saves: Mapped[Optional[int]]
    bonus: Mapped[Optional[int]]
    bps: Mapped[Optional[int]]
    ict_index: Mapped[Optional[Decimal]]
    expected_goals: Mapped[Optional[Decimal]]
    expected_assists: Mapped[Optional[Decimal]]
    expected_goal_involvements: Mapped[Optional[Decimal]]
    expected_goals_conceded: Mapped[Optional[Decimal]]
    value: Mapped[Optional[int]]  # price at the time, in tenths of a million
    selected: Mapped[Optional[int]]  # number of managers who owned the player
    transfers_in: Mapped[Optional[int]]
    transfers_out: Mapped[Optional[int]]
    transfers_balance: Mapped[Optional[int]]
    updated_at: Mapped[datetime] = updated_at()


class SyncRun(Base):
    """One run of a sync job, so the API can report freshness and jobs can skip work."""
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    kind: Mapped[str]  # "bootstrap" or "history"
    event_id: Mapped[Optional[int]]  # the gameweek a history run covered
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[Optional[datetime]]
    status: Mapped[str]  # "running", "succeeded" or "failed"
    error: Mapped[Optional[str]]
