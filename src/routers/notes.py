from typing import Annotated, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime
from sqlalchemy.orm import Session
from src.models.note import NoteRequest, NoteResponse, NotesPage
from src.services import notes
from src.util.auth import CurrentUser
from src.util.database import get_session

# The signed-in user's notes, synced across their devices. Like every route under
# /api/me: a Supabase access token is required, and responses are private, no-store.
notes_router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]


def note_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Note not found")


@notes_router.get("/me/notes")
def get_notes(
    user_id: CurrentUser,
    session: SessionDep,
    since: Annotated[Optional[str], Query(description="The cursor from the last call")] = None,
) -> NotesPage:
    """List the notes changed since the cursor, oldest first, deletions included.

    Without since, every note. Store the returned cursor and pass it next time; while
    more is true, call again straight away. A note can come back twice: apply it by
    id, newer updated_at winning. 422 for a cursor this API didn't return.
    """
    try:
        return notes.list_changes(session, user_id, since)
    except notes.InvalidCursorError as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor") from exc


@notes_router.put("/me/notes/{note_id}")
def put_note(
    note_id: UUID, body: NoteRequest, user_id: CurrentUser, session: SessionDep
) -> NoteResponse:
    """Create or update a note, deleting it if deleted_at is set.

    The newer updated_at wins: if the stored note is as new or newer, it's kept and
    returned, so compare the response with what you sent. 404 if the id is someone
    else's.
    """
    try:
        return notes.save_note(session, user_id, note_id, body)
    except notes.NoteNotFoundError as exc:
        raise note_not_found() from exc


@notes_router.delete("/me/notes/{note_id}", status_code=204)
def delete_note(
    note_id: UUID,
    user_id: CurrentUser,
    session: SessionDep,
    updated_at: Annotated[
        AwareDatetime, Query(description="When it was deleted on the device (ISO 8601, use Z)")
    ],
) -> None:
    """Delete a note as of updated_at, the same as a PUT with deleted_at set.

    204 even if a later change wins or it's already deleted. 404 if the note doesn't
    exist or is someone else's.
    """
    try:
        notes.delete_note(session, user_id, note_id, updated_at)
    except notes.NoteNotFoundError as exc:
        raise note_not_found() from exc
