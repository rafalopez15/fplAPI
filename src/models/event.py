from pydantic import BaseModel


class TopElementInfo(BaseModel):
    id: int
    points: int


class EventResponse(BaseModel):
    id: int
    name: str
    average_entry_score: int
    highest_scoring_entry: int
    deadline_time_epoch: int
    deadline_time_game_offset: int
    highest_score: int
    most_selected: int
    most_transferred_in: int
    top_element: int
    top_element_info: TopElementInfo
    transfers_made: int
    most_captained: int
    most_vice_captained: int
