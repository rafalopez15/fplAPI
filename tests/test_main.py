from unittest.mock import AsyncMock, Mock

import requests

from fastapi.testclient import TestClient
from main import app
from src.util import database
from src.util.fpl_service import FplService


def test_healthcheck(monkeypatch):
    monkeypatch.setattr(database, "is_database_reachable", lambda: True)
    response = TestClient(app).get("/healthcheck")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_healthcheck_database_unavailable(monkeypatch):
    monkeypatch.setattr(database, "is_database_reachable", lambda: False)
    response = TestClient(app).get("/healthcheck")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "unavailable"}


def test_lifespan_fetches_fpl_data_on_startup(monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr(FplService, "get_fpl_api_data", fetch)

    with TestClient(app):
        fetch.assert_awaited_once()


def test_healthcheck_hidden_from_schema():
    assert "/healthcheck" not in app.openapi()["paths"]


def test_app_starts_when_startup_fetch_fails(monkeypatch):
    monkeypatch.setattr(
        "src.util.fpl_service.requests.get",
        Mock(side_effect=requests.exceptions.ConnectionError("down")),
    )
    monkeypatch.setattr(database, "is_database_reachable", lambda: True)
    FplService().fpl_data = None

    with TestClient(app) as client:
        assert client.get("/healthcheck").status_code == 200
        assert client.get("/api/teams").status_code == 503
