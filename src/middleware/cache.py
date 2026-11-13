"""Cache-Control defaults, set on responses on their way out."""

from fastapi import Request
from src.util.auth import ACCOUNT_CACHE

SYNCED_CACHE = "s-maxage=300, stale-while-revalidate=3600"


async def never_cache_accounts(request: Request, call_next):
    """Mark every response under /api/me private, errors included.

    These hold one user's data. A shared cache header on one, from a route or a
    future default, would let Vercel's CDN serve it to someone else.
    """
    response = await call_next(request)
    if request.url.path == "/api/me" or request.url.path.startswith("/api/me/"):
        response.headers["Cache-Control"] = ACCOUNT_CACHE
    return response


async def cache_synced_data(request: Request, call_next):
    """Let Vercel's CDN cache successful GETs that set no Cache-Control.

    The data changes hourly, so a copy up to 5 minutes old is fine.
    """
    response = await call_next(request)
    if (
        request.method == "GET"
        and request.url.path.startswith("/api/")
        and response.status_code == 200
        and "cache-control" not in response.headers
    ):
        response.headers["Cache-Control"] = SYNCED_CACHE
    return response
