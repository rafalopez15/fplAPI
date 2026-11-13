"""The Cache-Control defaults in src/middleware/cache.py."""

import asyncio

import pytest
from fastapi import Request, Response
from sqlalchemy import delete
from src.db.models import SyncRun
from src.middleware.cache import SYNCED_CACHE, cache_synced_data

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
