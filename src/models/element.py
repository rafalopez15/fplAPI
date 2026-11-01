from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ElementResponse(BaseModel):
    """A player. FPL sends decimals as strings ("4.8"); float fields convert them."""
    # Identity
    id: int
    code: int
    first_name: str
    second_name: str
    web_name: str
    element_type: int
    team: int
    team_code: int
    photo: str

    # Availability
    status: str
    news: str
    news_added: Optional[datetime]
    chance_of_playing_next_round: Optional[int]
    chance_of_playing_this_round: Optional[int]

    # Price (in tenths of a million: 62 is £6.2m) and transfers
    now_cost: int
    cost_change_event: int
    cost_change_start: int
    selected_by_percent: float
    transfers_in_event: int
    transfers_out_event: int

    # Points
    total_points: int
    event_points: int
    points_per_game: float
    form: float
    ep_next: Optional[float]

    # Season stats
    minutes: int
    starts: int
    goals_scored: int
    assists: int
    clean_sheets: int
    goals_conceded: int
    saves: int
    bonus: int
    yellow_cards: int
    red_cards: int

    # Advanced stats
    expected_goals: float
    expected_assists: float
    expected_goal_involvements: float
    expected_goals_conceded: float
    ict_index: float
