from typing import Annotated, List, Optional
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

MAX_TEXT = 5000
MAX_PLAYERS = 15
# A positive id Postgres can store (its integer maximum, as in routers/params.py).
StoredId = Annotated[int, Field(gt=0, le=2_147_483_647)]


class NotePlayer(BaseModel):
    """A player on a note, with the name saved so the note shows without the player list."""

    id: StoredId  # the element id
    web_name: str = Field(max_length=50)


class NoteTransfer(BaseModel):
    """The transfer a transfer note is about. Costs are in tenths of a million."""

    player_in: NotePlayer
    player_out: NotePlayer
    cost: Optional[int] = None
    out_cost: Optional[int] = None  # the selling price
    time: AwareDatetime


class NoteRequest(BaseModel):
    """The body of PUT /api/me/notes/{id}: the whole note, as the device has it.

    Times need a timezone. Bump updated_at on every change, deleting and undoing a
    delete included: the newer updated_at wins.
    """

    text: str = Field(max_length=MAX_TEXT)  # "" is allowed
    gameweek: Optional[Annotated[int, Field(ge=1, le=38)]] = None
    players: List[NotePlayer] = Field(default=[], max_length=MAX_PLAYERS)
    transfer: Optional[NoteTransfer] = None
    manager_id: Optional[StoredId] = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    deleted_at: Optional[AwareDatetime] = None  # set to delete, null to undo


class NoteResponse(BaseModel):
    """A note as stored, built from a notes row. A deleted one has deleted_at set and
    its content cleared."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    text: str
    gameweek: Optional[int] = None
    players: List[NotePlayer]
    transfer: Optional[NoteTransfer] = None
    manager_id: Optional[int] = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    deleted_at: Optional[AwareDatetime] = None


class NotesPage(BaseModel):
    """GET /api/me/notes: changes oldest first, and the cursor for the next call."""

    notes: List[NoteResponse]
    cursor: str  # pass as ?since= next time
    more: bool  # true when another page is waiting: call again straight away
