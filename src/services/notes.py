"""Notes synced across a user's devices (FPL-49).

The device makes each note's id and stamps created_at and updated_at with its own
clock. Every write sends the whole note, and the newer updated_at wins, so devices
can sync in any order and retries are harmless. Deleting is a write too (deleted_at
set, content cleared), which lets other devices learn about it and an undo (a later
write with deleted_at null) bring the note back.

GET pages through the user's changes by synced_at, the server's time of each write.
"""

import base64
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID
from sqlalchemy import func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from src.db.models import Note
from src.models.note import NoteRequest, NoteResponse, NotesPage
from src.services.profiles import ensure_profile

PAGE_SIZE = 500
# The last page's cursor is held this far back, so a write whose transaction was
# still committing when the page was read is picked up next time. Writes are one
# short statement, so a few seconds is plenty; the device sees those notes twice,
# which is harmless because applying a note is idempotent.
LOOKBACK = timedelta(seconds=5)
NIL_ID = UUID(int=0)
# Content a tombstone keeps: none.
CLEARED = {"text": "", "players": [], "transfer": None}


class NoteNotFoundError(Exception):
    """Raised for a note that doesn't exist or belongs to someone else."""


class InvalidCursorError(Exception):
    """Raised for a ?since= value this API didn't produce."""


def encode_cursor(synced_at: datetime, note_id: UUID) -> str:
    raw = f"{synced_at.isoformat()}|{note_id}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        synced_at, note_id = (
            base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        )
        parsed = datetime.fromisoformat(synced_at)
        if parsed.tzinfo is None:
            raise ValueError("cursor time has no timezone")
        return parsed, UUID(note_id)
    except ValueError as exc:  # also covers bad base64 (binascii.Error) and bad UTF-8
        raise InvalidCursorError(cursor) from exc


def list_changes(session: Session, user_id: UUID, since: Optional[str]) -> NotesPage:
    """The user's notes written after the cursor, oldest first, deletions included.

    Without a cursor, every note. At most PAGE_SIZE per call; more is true when
    another page is waiting. Raises InvalidCursorError for a cursor it didn't issue.
    """
    query = select(Note).where(Note.user_id == user_id)
    if since is not None:
        query = query.where(tuple_(Note.synced_at, Note.id) > decode_cursor(since))
    rows = session.scalars(
        query.order_by(Note.synced_at, Note.id).limit(PAGE_SIZE + 1)
    ).all()
    more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    if more:
        cursor = (rows[-1].synced_at, rows[-1].id)
    else:
        # clock_timestamp(), like the writes: now() is when the transaction began.
        held_back = (session.scalar(select(func.clock_timestamp())) - LOOKBACK, NIL_ID)
        last = (rows[-1].synced_at, rows[-1].id) if rows else held_back
        cursor = min(last, held_back)
        if since is not None:
            # Never move backwards past where the device already was.
            cursor = max(cursor, decode_cursor(since))
    return NotesPage(
        notes=[NoteResponse.model_validate(row) for row in rows],
        cursor=encode_cursor(*cursor),
        more=more,
    )


def save_note(
    session: Session, user_id: UUID, note_id: UUID, note: NoteRequest
) -> NoteResponse:
    """Create or update a note, unless the stored one is as new or newer.

    Returns the stored note either way, so the device can tell whether it won.
    Raises NoteNotFoundError if the id belongs to another user.
    """
    values = note.model_dump(mode="json") | {"user_id": user_id}
    for name in ("created_at", "updated_at", "deleted_at"):
        values[name] = getattr(note, name)
    if note.deleted_at is not None:
        values |= CLEARED
    ensure_profile(session, user_id)
    statement = insert(Note).values(
        id=note_id, synced_at=func.clock_timestamp(), **values
    )
    statement = statement.on_conflict_do_update(
        index_elements=[Note.id],
        set_={
            name: statement.excluded[name]
            for name in (*values, "synced_at")
            if name != "user_id"
        },
        # Only the owner's notes, and only when this write is newer.
        where=(Note.user_id == user_id)
        & (Note.updated_at < statement.excluded.updated_at),
    )
    written = session.scalars(
        statement.returning(Note), execution_options={"populate_existing": True}
    ).one_or_none()
    stored = written or _owned(session, user_id, note_id)
    result = NoteResponse.model_validate(stored)
    session.commit()
    return result


def delete_note(
    session: Session, user_id: UUID, note_id: UUID, updated_at: datetime
) -> None:
    """Delete a note as of updated_at (device time), unless it changed later since.

    A delete that loses, or of a note already deleted, does nothing. Raises
    NoteNotFoundError if the note doesn't exist or belongs to another user.
    """
    deleted = session.execute(
        update(Note)
        .where(
            Note.id == note_id, Note.user_id == user_id, Note.updated_at < updated_at
        )
        .values(
            deleted_at=updated_at,
            updated_at=updated_at,
            synced_at=func.clock_timestamp(),
            **CLEARED,
        )
    ).rowcount
    if not deleted:
        _owned(session, user_id, note_id)
    session.commit()


def _owned(session: Session, user_id: UUID, note_id: UUID) -> Note:
    """The user's stored note. Another user's note is treated as missing."""
    note = session.get(Note, note_id, populate_existing=True)
    if note is None or note.user_id != user_id:
        raise NoteNotFoundError(note_id)
    return note
