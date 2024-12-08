from pydantic import BaseModel


class ElementResponse(BaseModel):
    element_type: int
    event_points: int
    first_name: str
    form: str
    id: int
    news: str
    now_cost: int
    points_per_game: str
    second_name: str
    selected_by_percent: str
    status: str
    team: int
    team_code: int
    total_points: int
    web_name: str
