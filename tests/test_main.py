from datetime import datetime, timezone

from fastapi.testclient import TestClient
from main import app
from src.util import database

LAST_SYNC = {
    "bootstrap": datetime(2026, 11, 2, 1, 17, 42, tzinfo=timezone.utc),
    "event_points": datetime(2026, 11, 1, 3, 17, 50, tzinfo=timezone.utc),
}


def test_healthcheck(monkeypatch):
    monkeypatch.setattr(database, "is_database_reachable", lambda: True)
    monkeypatch.setattr(
        database, "get_last_sync", lambda kind="bootstrap": LAST_SYNC[kind]
    )
    response = TestClient(app).get("/healthcheck")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "last_sync": "2026-11-02T01:17:42+00:00",
        "last_points_sync": "2026-11-01T03:17:50+00:00",
    }


def test_healthcheck_before_the_first_sync(monkeypatch):
    monkeypatch.setattr(database, "is_database_reachable", lambda: True)
    monkeypatch.setattr(database, "get_last_sync", lambda kind="bootstrap": None)
    body = TestClient(app).get("/healthcheck").json()
    assert (body["last_sync"], body["last_points_sync"]) == (None, None)


def test_healthcheck_database_unavailable(monkeypatch):
    def unexpected(kind="bootstrap"):
        raise AssertionError(
            f"get_last_sync({kind}) shouldn't run when the database is down"
        )

    monkeypatch.setattr(database, "is_database_reachable", lambda: False)
    monkeypatch.setattr(database, "get_last_sync", unexpected)
    response = TestClient(app).get("/healthcheck")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "unavailable",
        "last_sync": None,
        "last_points_sync": None,
    }


def test_healthcheck_hidden_from_schema():
    assert "/healthcheck" not in app.openapi()["paths"]


def test_app_starts_without_calling_fpl():
    # block_network fails the test if startup makes any FPL request.
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200
