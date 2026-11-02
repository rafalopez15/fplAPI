from datetime import datetime, timezone

from fastapi.testclient import TestClient
from main import app
from src.util import database

LAST_SYNC = datetime(2026, 11, 2, 1, 17, 42, tzinfo=timezone.utc)


def test_healthcheck(monkeypatch):
    monkeypatch.setattr(database, "is_database_reachable", lambda: True)
    monkeypatch.setattr(database, "get_last_sync", lambda: LAST_SYNC)
    response = TestClient(app).get("/healthcheck")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "last_sync": "2026-11-02T01:17:42+00:00",
    }


def test_healthcheck_before_the_first_sync(monkeypatch):
    monkeypatch.setattr(database, "is_database_reachable", lambda: True)
    monkeypatch.setattr(database, "get_last_sync", lambda: None)
    assert TestClient(app).get("/healthcheck").json()["last_sync"] is None


def test_healthcheck_database_unavailable(monkeypatch):
    def unexpected():
        raise AssertionError("get_last_sync shouldn't run when the database is down")

    monkeypatch.setattr(database, "is_database_reachable", lambda: False)
    monkeypatch.setattr(database, "get_last_sync", unexpected)
    response = TestClient(app).get("/healthcheck")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "unavailable", "last_sync": None}


def test_healthcheck_hidden_from_schema():
    assert "/healthcheck" not in app.openapi()["paths"]


def test_app_starts_without_calling_fpl():
    # block_network fails the test if startup makes any FPL request.
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200
