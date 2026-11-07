from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ElementResponse(BaseModel):
    """A player, built from an elements row. Decimal columns are returned as floats.

    Only the fields the app can't work without are required. The rest default to
    None, so if FPL drops a field or starts sending null for it, the endpoints
    return null for that field instead of failing.
    """

    model_config = ConfigDict(from_attributes=True)

    # Required
    id: int
    web_name: str
    team: int
    element_type: int
    now_cost: int  # in tenths of a million: 62 is £6.2m
    status: str

    # Identity
    code: Optional[int] = None
    first_name: Optional[str] = None
    second_name: Optional[str] = None
    team_code: Optional[int] = None
    photo: Optional[str] = None

    # Availability
    news: Optional[str] = None
    news_added: Optional[datetime] = None
    chance_of_playing_next_round: Optional[int] = None
    chance_of_playing_this_round: Optional[int] = None
    # False for players who can't be picked: left the club, released, not in the squad.
    # The API never filters them out; the app decides what to hide.
    can_select: Optional[bool] = None
    can_transact: Optional[bool] = None
    removed: Optional[bool] = None

    # Price changes and transfers
    cost_change_event: Optional[int] = None
    cost_change_start: Optional[int] = None
    selected_by_percent: Optional[float] = None
    transfers_in_event: Optional[int] = None
    transfers_out_event: Optional[int] = None

    # Points
    total_points: Optional[int] = None
    event_points: Optional[int] = None
    points_per_game: Optional[float] = None
    form: Optional[float] = None
    ep_next: Optional[float] = None

    # Season stats
    minutes: Optional[int] = None
    starts: Optional[int] = None
    goals_scored: Optional[int] = None
    assists: Optional[int] = None
    clean_sheets: Optional[int] = None
    goals_conceded: Optional[int] = None
    saves: Optional[int] = None
    bonus: Optional[int] = None
    yellow_cards: Optional[int] = None
    red_cards: Optional[int] = None

    # Advanced stats
    expected_goals: Optional[float] = None
    expected_assists: Optional[float] = None
    expected_goal_involvements: Optional[float] = None
    expected_goals_conceded: Optional[float] = None
    ict_index: Optional[float] = None
