"""Cache-Control defaults, set on responses on their way out."""

from fastapi import Request
from src.util.auth import ACCOUNT_CACHE


async def never_cache_accounts(request: Request, call_next):
    """Mark every response under /api/me private, errors included.

    These hold one user's data. A shared cache header on one, from a route or a
    future default, would let Vercel's CDN serve it to someone else.
    """
    response = await call_next(request)
    if request.url.path == "/api/me" or request.url.path.startswith("/api/me/"):
        response.headers["Cache-Control"] = ACCOUNT_CACHE
    return response

