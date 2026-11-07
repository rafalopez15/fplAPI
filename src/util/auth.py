"""Who's calling: checks the Supabase sign-in token on account routes.

Supabase signs access tokens with an asymmetric key and publishes the public half
at a JWKS URL, so the API checks tokens locally. The key set is cached in memory for
5 minutes; Supabase is only called on a cold start, after that, or for an unknown
key id.
FPL routes never use this, so they work the same with or without a token.
"""

import logging
from typing import Annotated, Optional
from uuid import UUID
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from src.util.config import SUPABASE_URL

logger = logging.getLogger(__name__)

# Never the token's own "alg" header: that would let a forged token pick HS256.
ALGORITHMS = ["ES256", "RS256"]
AUDIENCE = "authenticated"
JWKS_TIMEOUT = 5  # seconds; someone in the app is waiting
ACCOUNT_CACHE = "private, no-store"

ISSUER = f"{SUPABASE_URL}/auth/v1" if SUPABASE_URL else None
# Only the key set cache (refetched every 5 minutes), not cache_keys: that caches
# each key with no expiry, so a key revoked in Supabase would keep working.
jwks_client = (
    jwt.PyJWKClient(f"{ISSUER}/.well-known/jwks.json", timeout=JWKS_TIMEOUT)
    if ISSUER
    else None
)

# auto_error=False, so a missing header gets our 401 rather than FastAPI's 403.
bearer = HTTPBearer(auto_error=False)


def not_signed_in() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Not signed in",
        headers={"WWW-Authenticate": "Bearer", "Cache-Control": ACCOUNT_CACHE},
    )


def sign_in_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Sign-in is unavailable right now",
        headers={"Cache-Control": ACCOUNT_CACHE},
    )


def get_current_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer)],
) -> UUID:
    """FastAPI dependency: the signed-in user's id (the token's sub).

    Raises 401 for a missing, malformed, expired or forged token, and 503 if
    SUPABASE_URL isn't set or Supabase's keys can't be fetched.
    """
    if jwks_client is None:
        raise sign_in_unavailable()
    if credentials is None:
        raise not_signed_in()
    token = credentials.credentials
    try:
        key = jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=ALGORITHMS,
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "sub", "aud", "iss"]},
        )
        return UUID(claims["sub"])
    except (jwt.PyJWKClientConnectionError, jwt.PyJWKSetError) as exc:
        # The URL isn't secret, and a wrong SUPABASE_URL shows up here as a 401.
        logger.warning(
            "Couldn't fetch Supabase's signing keys from %s: %s", jwks_client.uri, exc
        )
        raise sign_in_unavailable() from exc
    # PyJWKClientError here is a key id Supabase doesn't have: a forged token.
    except (jwt.InvalidTokenError, jwt.PyJWKClientError, ValueError) as exc:
        logger.info("Rejected a sign-in token: %s", exc)
        raise not_signed_in() from exc


CurrentUser = Annotated[UUID, Depends(get_current_user)]
