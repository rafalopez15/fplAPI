"""Supabase's Auth Admin API, for deleting accounts. Needs the project's secret key.

Separate from fpl_client.py, which is only for FPL. The key goes in the apikey and
Authorization headers, as Supabase's own clients send it, and is never logged.
"""
import logging
from typing import NoReturn, Optional
from uuid import UUID
import requests
from src.util.config import SUPABASE_SECRET_KEY, SUPABASE_URL

logger = logging.getLogger(__name__)

# (connect, read) seconds. DELETE /api/me holds a transaction open while this runs,
# and a single number would apply to each part separately.
TIMEOUT = (3, 5)


class SupabaseAdminError(Exception):
    """Raised when the Admin API isn't configured, can't be reached or refuses."""


def delete_user(user_id: UUID) -> None:
    """Delete the user from Supabase Auth. A user that's already gone counts as done."""
    if not (SUPABASE_URL and SUPABASE_SECRET_KEY):
        _fail(user_id, "SUPABASE_URL or SUPABASE_SECRET_KEY isn't set")
    try:
        response = requests.delete(
            f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
            headers={"apikey": SUPABASE_SECRET_KEY,
                     "Authorization": f"Bearer {SUPABASE_SECRET_KEY}"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        _fail(user_id, f"Supabase couldn't be reached: {type(exc).__name__}", exc)
    if response.ok or _user_not_found(response):
        return
    # Status only: the body could echo the request.
    _fail(user_id, f"Supabase answered {response.status_code}")


def _user_not_found(response) -> bool:
    """Whether a 404 means the user is gone, not a wrong URL (which must not count as
    deleted). Supabase answers {"error_code": "user_not_found", ...}."""
    if response.status_code != 404:
        return False
    try:
        return response.json().get("error_code") == "user_not_found"
    except (ValueError, AttributeError):  # not JSON, or not an object
        return False


def _fail(user_id: UUID, reason: str, cause: Optional[Exception] = None) -> NoReturn:
    """Log why deleting the user failed, then raise. Never logs the key or a body."""
    logger.warning("Couldn't delete Supabase user %s: %s", user_id, reason)
    raise SupabaseAdminError(reason) from cause
