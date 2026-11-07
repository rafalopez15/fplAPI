"""Supabase's Auth Admin API, for deleting accounts. Needs the project's secret key.

Separate from fpl_client.py, which is only for FPL. The key goes in the apikey and
Authorization headers, as Supabase's own clients send it, and is never logged.
"""
import logging
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
        raise SupabaseAdminError("SUPABASE_URL or SUPABASE_SECRET_KEY isn't set")
    try:
        response = requests.delete(
            f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
            headers={"apikey": SUPABASE_SECRET_KEY,
                     "Authorization": f"Bearer {SUPABASE_SECRET_KEY}"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise SupabaseAdminError(f"Supabase couldn't be reached: {type(exc).__name__}") from exc
    if response.ok or response.status_code == 404:
        return
    # Status only: the body could echo the request.
    raise SupabaseAdminError(f"Supabase answered {response.status_code}")
