"""The middleware in src/middleware/: Cache-Control defaults, and the request
context for recording FPL calls."""

import asyncio
import re

import pytest
from fastapi import Request, Response
from sqlalchemy import delete
from src.db.models import SyncRun
from src.middleware.cache import SYNCED_CACHE, cache_synced_data
from src.middleware.fpl_calls import FplCallContext, client_of
from src.util import fpl_client
from src.util.fpl_metrics import endpoint_of
from tests.conftest import (
    make_fixture,
    make_fpl_event_live,
    make_fpl_history,
    make_fpl_league_standings,
    make_fpl_manager,
    make_fpl_picks,
    make_fpl_transfers,
)
from tests.test_fpl_metrics import response as fpl_response

# Seeded ids, so each answers 200.
SYNCED_PATHS = [
    "/api/elements",
    "/api/elements/1",
    "/api/elements/position/3",
    "/api/events",
    "/api/events/9",
    "/api/events/current-event/",
    "/api/teams",
    "/api/teams/Arsenal",
    "/api/fixtures",
]


@pytest.mark.parametrize("path", SYNCED_PATHS)
def test_synced_routes_are_cached(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == SYNCED_CACHE


@pytest.mark.parametrize(
    "path, status", [("/api/teams/Nope", 404), ("/api/elements/0", 422)]
)
def test_errors_are_not_cached(client, path, status):
    response = client.get(path)
    assert response.status_code == status
    assert "cache-control" not in response.headers


def test_503_is_not_cached(client, seeded_session):
    seeded_session.execute(delete(SyncRun))
    response = client.get("/api/teams")
    assert response.status_code == 503
    assert "cache-control" not in response.headers


def test_only_gets_are_cached():
    # No route answers anything but GET with a 200 outside /api/me yet, so the
    # middleware is called directly.
    request = Request(
        {"type": "http", "method": "OPTIONS", "path": "/api/teams", "headers": []}
    )

    async def call_next(_request):
        return Response(status_code=200)

    response = asyncio.run(cache_synced_data(request, call_next))
    assert "cache-control" not in response.headers


# --- FPL call context ----------------------------------------------------------

PAYLOADS = {
    "entry/{id}": make_fpl_manager,
    "entry/{id}/transfers": make_fpl_transfers,
    "entry/{id}/history": make_fpl_history,
    "entry/{id}/event/{gw}/picks": make_fpl_picks,
    "event/{gw}/live": make_fpl_event_live,
    "fixtures": lambda: [make_fixture(started=True)],
    "leagues-classic/{id}/standings": make_fpl_league_standings,
}


@pytest.fixture
def fpl(monkeypatch):
    """Answer every FPL URL with its conftest payload."""

    def get(url, **_kwargs):
        endpoint, _ = endpoint_of(url)
        return fpl_response(payload=PAYLOADS[endpoint]())

    monkeypatch.setattr(fpl_client.requests, "get", get)


@pytest.mark.parametrize(
    "user_agent, client",
    [
        ("FPL/42 CFNetwork/1568.100.1 Darwin/24.0.0", "ios"),
        ("fpl-social-web", "web"),
        ("fpl-social-smoke-test", "smoke-test"),
        ("curl/8.7.1 fpl-social-contract", "contract"),
        ("Mozilla/5.0 (Macintosh)", "other"),
        ("", "other"),
    ],
)
def test_client_from_user_agent(user_agent, client):
    assert client_of(user_agent) == client


ROUTE_CALLS = [
    (
        "/api/managers/7700093",
        "GET /api/managers/{manager_id}",
        [("entry/{id}", None)],
    ),
    (
        "/api/managers/7700093/transfers",
        "GET /api/managers/{manager_id}/transfers",
        [("entry/{id}/transfers", None), ("entry/{id}/history", None)],
    ),
    (
        "/api/managers/7700093/picks",
        "GET /api/managers/{manager_id}/picks",
        [("entry/{id}", None), ("entry/{id}/event/{gw}/picks", 9)],
    ),
    ("/api/events/9/live", "GET /api/events/{event_id}/live", [("event/{gw}/live", 9)]),
    (
        "/api/events/9/fixtures",
        "GET /api/events/{event_id}/fixtures",
        [("fixtures", 9)],
    ),
    (
        "/api/leagues/5508",
        "GET /api/leagues/{league_id}",
        [("leagues-classic/{id}/standings", None)],
    ),
]


@pytest.mark.usefixtures("fpl")
@pytest.mark.parametrize("path, caller, calls", ROUTE_CALLS)
def test_routes_record_their_template_and_client(
    client, fpl_calls, path, caller, calls
):
    answer = client.get(path, headers={"User-Agent": "FPL/42 CFNetwork"})

    assert answer.status_code == 200
    assert [(row["endpoint"], row["event"]) for row in fpl_calls] == calls
    for row in fpl_calls:
        assert (row["caller"], row["client"]) == (caller, "ios")
        # No id from the request path, or any other number, is stored.
        assert not re.search(r"\d", row["endpoint"] + row["caller"])


@pytest.mark.usefixtures("fpl")
def test_account_routes_record_their_template(client, fpl_calls, signed_in):
    client.headers.update(signed_in())
    client.get("/api/me")
    answer = client.put("/api/me/teams/7700093", json={"relation": "following"})

    assert answer.status_code == 200
    assert [(row["caller"], row["client"]) for row in fpl_calls] == [
        ("PUT /api/me/teams/{manager_id}", "other")
    ]


def test_other_scopes_pass_through():
    received = []

    async def app(scope, _receive, _send):
        received.append(scope["type"])

    asyncio.run(FplCallContext(app)({"type": "lifespan"}, None, None))
    assert received == ["lifespan"]
