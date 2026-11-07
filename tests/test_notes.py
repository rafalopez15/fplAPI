# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""Synced notes: /api/me/notes and services/notes.py."""

import base64
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from src.db.models import Note, Profile
from src.services import notes
from tests.conftest import USER_ID

T0 = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
OTHER_USER = uuid4()


def iso(moment):
    return moment.isoformat().replace("+00:00", "Z")


def note_body(minutes=0, **overrides):
    """A transfer note as the device sends it, last changed T0 + minutes."""
    body = {
        "text": "Isak's minutes look safe",
        "gameweek": 9,
        "players": [{"id": 2, "web_name": "Haaland"}],
        "transfer": {
            "player_in": {"id": 2, "web_name": "Haaland"},
            "player_out": {"id": 1, "web_name": "Saka"},
            "cost": 145,
            "out_cost": 90,
            "time": "2026-10-31T10:08:30.794468Z",
        },
        "created_at": iso(T0),
        "updated_at": iso(T0 + timedelta(minutes=minutes)),
    }
    body.update(overrides)
    return body


@pytest.fixture
def api(client, signed_in):
    """The client, with the signed-in user's headers on every request."""
    client.headers.update(signed_in())
    return client


def put(api, note_id, **body):
    return api.put(f"/api/me/notes/{note_id}", json=note_body(**body))


def changes(api, since=None):
    params = {"since": since} if since else {}
    response = api.get("/api/me/notes", params=params)
    assert response.status_code == 200
    return response.json()


def ids(page):
    return [UUID(n["id"]) for n in page["notes"]]


@pytest.fixture
def no_lookback(monkeypatch):
    """Cursors exactly at the last note, so tests can tell new changes from old."""
    monkeypatch.setattr(notes, "LOOKBACK", timedelta(0))


# --- writing -------------------------------------------------------------------


def test_put_creates_a_note_and_returns_it(api):
    note_id = uuid4()
    response = put(api, note_id)
    assert response.status_code == 200
    body = response.json()
    sent = note_body()
    assert body["id"] == str(note_id)
    assert {k: body[k] for k in ("text", "gameweek", "players", "transfer")} == {
        k: sent[k] for k in ("text", "gameweek", "players", "transfer")
    }
    assert (body["manager_id"], body["deleted_at"]) == (None, None)
    assert ids(changes(api)) == [note_id]


def test_put_before_get_me_creates_the_profile(api, seeded_session):
    assert put(api, uuid4()).status_code == 200
    assert seeded_session.get(Profile, UUID(USER_ID)) is not None


@pytest.mark.parametrize(
    "overrides",
    [
        {"text": ""},  # a skipped transfer note
        {"text": "x" * 5000},
        {"gameweek": None},
        {"players": [], "transfer": None},
        {"manager_id": 1},
        {
            "transfer": {
                "player_in": {"id": 2, "web_name": "Haaland"},
                "player_out": {"id": 1, "web_name": "Saka"},
                "time": "2026-10-31T10:08:30Z",
            }
        },
    ],
)
def test_put_accepts_what_the_device_can_send(api, overrides):
    assert put(api, uuid4(), **overrides).status_code == 200


def test_newer_put_updates_the_note(api):
    note_id = uuid4()
    put(api, note_id)
    body = put(api, note_id, minutes=5, text="Changed my mind").json()
    assert body["text"] == "Changed my mind"
    assert body["updated_at"] == iso(T0 + timedelta(minutes=5))


@pytest.mark.parametrize("minutes", [-5, 0])  # older, and a retry of the same write
def test_older_or_equal_put_keeps_the_stored_note(api, minutes):
    note_id = uuid4()
    put(api, note_id, text="Kept")
    body = put(api, note_id, minutes=minutes, text="Lost").json()
    assert body["text"] == "Kept"
    assert [n["text"] for n in changes(api)["notes"]] == ["Kept"]


def test_put_on_someone_elses_note_is_404_and_changes_nothing(client, signed_in):
    note_id = uuid4()
    client.put(
        f"/api/me/notes/{note_id}",
        json=note_body(text="Theirs"),
        headers=signed_in(OTHER_USER),
    )
    response = client.put(
        f"/api/me/notes/{note_id}",
        json=note_body(minutes=5, text="Mine"),
        headers=signed_in(),
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Note not found"}
    theirs = client.get("/api/me/notes", headers=signed_in(OTHER_USER)).json()["notes"]
    assert [n["text"] for n in theirs] == ["Theirs"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"text": "x" * 5001},
        {"text": None},
        {"gameweek": 0},
        {"gameweek": 39},
        {"players": [{"id": i, "web_name": "P"} for i in range(1, 17)]},
        {"players": [{"id": 0, "web_name": "P"}]},
        {"players": [{"id": 2, "web_name": "x" * 51}]},
        {"manager_id": 2_147_483_648},
        {"updated_at": "2026-11-01T10:00:00"},  # no timezone
        {"created_at": None},
        {"transfer": {"player_in": {"id": 2, "web_name": "Haaland"}}},
    ],
)
def test_invalid_note_is_422(api, overrides):
    assert put(api, uuid4(), **overrides).status_code == 422


def test_bad_note_id_is_422(api):
    assert api.put("/api/me/notes/not-a-uuid", json=note_body()).status_code == 422


# --- deleting and undoing ------------------------------------------------------


def test_put_with_deleted_at_leaves_a_tombstone(api):
    note_id = uuid4()
    put(api, note_id)
    body = put(
        api, note_id, minutes=5, deleted_at=iso(T0 + timedelta(minutes=5))
    ).json()
    assert body["deleted_at"] == iso(T0 + timedelta(minutes=5))
    # The content is cleared: undoing sends the whole note again.
    assert (body["text"], body["players"], body["transfer"]) == ("", [], None)
    assert changes(api)["notes"][0]["deleted_at"] is not None


def test_delete_route_then_put_brings_the_note_back(api):
    note_id = uuid4()
    put(api, note_id)
    response = api.delete(
        f"/api/me/notes/{note_id}",
        params={"updated_at": iso(T0 + timedelta(minutes=5))},
    )
    assert response.status_code == 204
    assert response.content == b""
    [tombstone] = changes(api)["notes"]
    assert (tombstone["deleted_at"], tombstone["text"]) == (
        iso(T0 + timedelta(minutes=5)),
        "",
    )

    body = put(api, note_id, minutes=6).json()  # undo: same id, later updated_at
    assert body["deleted_at"] is None
    assert body["text"] == note_body()["text"]


def test_delete_older_than_the_last_change_does_nothing(api):
    note_id = uuid4()
    put(api, note_id, minutes=10)
    response = api.delete(f"/api/me/notes/{note_id}", params={"updated_at": iso(T0)})
    assert response.status_code == 204
    assert changes(api)["notes"][0]["deleted_at"] is None


def test_deleting_twice_is_204(api):
    note_id = uuid4()
    put(api, note_id)
    for minutes in (5, 5, 6):
        response = api.delete(
            f"/api/me/notes/{note_id}",
            params={"updated_at": iso(T0 + timedelta(minutes=minutes))},
        )
        assert response.status_code == 204


def test_deleting_a_missing_note_is_404(api):
    response = api.delete(f"/api/me/notes/{uuid4()}", params={"updated_at": iso(T0)})
    assert response.status_code == 404
    assert response.json() == {"detail": "Note not found"}


def test_deleting_someone_elses_note_is_404_and_changes_nothing(client, signed_in):
    note_id = uuid4()
    client.put(
        f"/api/me/notes/{note_id}", json=note_body(), headers=signed_in(OTHER_USER)
    )
    response = client.delete(
        f"/api/me/notes/{note_id}",
        headers=signed_in(),
        params={"updated_at": iso(T0 + timedelta(minutes=5))},
    )
    assert response.status_code == 404
    theirs = client.get("/api/me/notes", headers=signed_in(OTHER_USER)).json()["notes"]
    assert theirs[0]["deleted_at"] is None


@pytest.mark.parametrize("params", [{}, {"updated_at": "2026-11-01T10:00:00"}])
def test_delete_needs_a_time_with_a_timezone(api, params):
    assert api.delete(f"/api/me/notes/{uuid4()}", params=params).status_code == 422


# --- reading changes -----------------------------------------------------------


def test_no_notes(api):
    page = changes(api)
    assert (page["notes"], page["more"]) == ([], False)
    assert page["cursor"]


def test_users_only_see_their_own_notes(client, signed_in):
    client.put(
        f"/api/me/notes/{uuid4()}", json=note_body(), headers=signed_in(OTHER_USER)
    )
    assert client.get("/api/me/notes", headers=signed_in()).json()["notes"] == []


@pytest.mark.usefixtures("no_lookback")
def test_since_returns_only_later_changes(api):
    first, second = uuid4(), uuid4()
    put(api, first)
    cursor = changes(api)["cursor"]
    put(api, second)
    assert ids(changes(api, cursor)) == [second]
    put(api, first, minutes=5)  # an edit counts as a change
    assert ids(changes(api, cursor)) == [second, first]


def test_recent_changes_come_back_once_more(api, seeded_session):
    # The cursor stays LOOKBACK behind, so a write still committing when the page
    # was read isn't missed. Older writes don't come back.
    recent, old = uuid4(), uuid4()
    put(api, old)
    put(api, recent)
    seeded_session.execute(
        update(Note)
        .where(Note.id == old)
        .values(synced_at=datetime.now(timezone.utc) - timedelta(hours=1))
    )
    cursor = changes(api)["cursor"]
    assert ids(changes(api, cursor)) == [recent]


@pytest.mark.usefixtures("no_lookback")
def test_cursor_never_moves_back_past_since(api, monkeypatch):
    note_id = uuid4()
    put(api, note_id)
    cursor = changes(api)["cursor"]
    monkeypatch.setattr(notes, "LOOKBACK", timedelta(hours=1))
    page = changes(api, cursor)
    assert page["notes"] == []
    assert page["cursor"] == cursor


@pytest.mark.usefixtures("no_lookback")
def test_pages(api, monkeypatch):
    monkeypatch.setattr(notes, "PAGE_SIZE", 2)
    written = [uuid4() for _ in range(3)]
    for note_id in written:
        put(api, note_id)
    first = changes(api)
    assert (ids(first), first["more"]) == (written[:2], True)
    second = changes(api, first["cursor"])
    assert (ids(second), second["more"]) == (written[2:], False)


@pytest.mark.usefixtures("no_lookback")
def test_notes_written_at_the_same_moment_are_all_returned(
    api, monkeypatch, seeded_session
):
    monkeypatch.setattr(notes, "PAGE_SIZE", 1)
    written = [uuid4() for _ in range(3)]
    for note_id in written:
        put(api, note_id)
    seeded_session.execute(update(Note).values(synced_at=T0))
    seen, page = [], changes(api)
    seen += ids(page)
    while page["more"]:
        page = changes(api, page["cursor"])
        seen += ids(page)
    assert sorted(seen) == sorted(written)


@pytest.mark.parametrize(
    "cursor",
    [
        "garbage!",
        base64.urlsafe_b64encode(b"not-a-time|not-a-uuid").decode(),
        base64.urlsafe_b64encode(
            f"2026-11-01T10:00:00|{uuid4()}".encode()
        ).decode(),  # no tz
        base64.urlsafe_b64encode(b"\xff\xfe").decode(),
    ],
)
def test_invalid_cursor_is_422(api, cursor):
    response = api.get("/api/me/notes", params={"since": cursor})
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid cursor"}


# --- table ---------------------------------------------------------------------


def test_deleting_a_profile_deletes_its_notes(api, seeded_session):
    put(api, uuid4())
    seeded_session.delete(seeded_session.get(Profile, UUID(USER_ID)))
    seeded_session.flush()
    seeded_session.expire_all()
    assert seeded_session.scalars(select(Note)).all() == []
