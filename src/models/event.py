from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, model_validator


class TopElementInfo(BaseModel):
    id: int
    points: int


class ChipPlay(BaseModel):
    chip_name: str
    num_played: int


class EventResponse(BaseModel):
    """A gameweek, built from an events row.

    The stats are null for gameweeks that haven't been played yet.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    deadline_time: datetime
    deadline_time_epoch: int
    deadline_time_game_offset: Optional[int] = None
    release_time: Optional[datetime] = None
    finished: bool
    data_checked: bool
    is_previous: bool
    is_current: bool
    is_next: bool

    average_entry_score: Optional[int] = None
    highest_score: Optional[int] = None
    highest_scoring_entry: Optional[int] = None
    transfers_made: Optional[int] = None
    most_selected: Optional[int] = None
    most_transferred_in: Optional[int] = None
    most_captained: Optional[int] = None
    most_vice_captained: Optional[int] = None
    top_element: Optional[int] = None
    top_element_info: Optional[TopElementInfo] = None
    chip_plays: Optional[list[ChipPlay]] = None

    @model_validator(mode="before")
    @classmethod
    def rebuild_top_element_info(cls, data: Any) -> Any:
        """Rebuild FPL's top_element_info from the two columns it's stored in."""
        if not hasattr(data, "top_element_points"):
            return data
        fields = {name: getattr(data, name) for name in cls.model_fields if hasattr(data, name)}
        if data.top_element is not None and data.top_element_points is not None:
            fields["top_element_info"] = {"id": data.top_element, "points": data.top_element_points}
        return fields


class LiveElementResponse(BaseModel):
    """One player's result in a gameweek, from FPL's event/{gw}/live/ stats.

    minutes tells "0 points, didn't play" (0 minutes) from "0 points, played".
    """
    id: int
    total_points: Optional[int] = None
    minutes: Optional[int] = None
