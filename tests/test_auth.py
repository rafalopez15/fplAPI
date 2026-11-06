# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""Sign-in tokens (util/auth.py) and the account routes under /api/me."""
import importlib.util
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from main import app
from src.db.models import Profile
from src.services import profiles
from src.util import auth, config, database

ISSUER = "https://test-ref.supabase.co/auth/v1"
KEY_ID = "test-key"


class FakeJwksClient:
    """Stands in for PyJWKClient: serves one public key, or raises a set error."""

    uri = f"{ISSUER}/.well-known/jwks.json"

    def __init__(self, public_key, error=None):
        self.public_key = public_key
        self.error = error

    def get_signing_key_from_jwt(self, token):
        if self.error:
            raise self.error
        if jwt.get_unverified_header(token).get("kid") != KEY_ID:
            raise jwt.PyJWKClientError("Unable to find a signing key that matches")
        return SimpleNamespace(key=self.public_key)


@pytest.fixture
def signing_key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def jwks(monkeypatch, signing_key):
    """Configure sign-in as if SUPABASE_URL were set, with a local key pair."""
    client = FakeJwksClient(signing_key.public_key())
    monkeypatch.setattr(auth, "ISSUER", ISSUER)
    monkeypatch.setattr(auth, "jwks_client", client)
    return client


def make_token(key, algorithm="ES256", headers=None, **claims):
    """A token shaped like a Supabase access token. Claims set to None are left out."""
    payload = {
        "sub": "6f1d3c2a-8b4e-4f5a-9c7d-1e2f3a4b5c6d", "aud": "authenticated",
        "iss": ISSUER, "exp": int(time.time()) + 3600, "role": "authenticated",
        "email": "fpl.social.test@gmail.com", **claims,
    }
    payload = {name: value for name, value in payload.items() if value is not None}
    return jwt.encode(payload, key, algorithm=algorithm, headers={"kid": KEY_ID, **(headers or {})})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# --- tokens --------------------------------------------------------------------

@pytest.mark.usefixtures("jwks")
def test_valid_token_returns_the_profile(client, signing_key, seeded_session):
    response = client.get("/api/me", headers=bearer(make_token(signing_key)))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert body["id"] == "6f1d3c2a-8b4e-4f5a-9c7d-1e2f3a4b5c6d"
    assert seeded_session.get(Profile, UUID(body["id"])) is not None


@pytest.mark.usefixtures("jwks")
@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Basic dXNlcjpwYXNz"},
    {"Authorization": "Bearer"},
    {"Authorization": "Bearer not-a-token"},
])
def test_missing_or_malformed_token_is_401(client, headers):
    response = client.get("/api/me", headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "Not signed in"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.usefixtures("jwks")
@pytest.mark.parametrize("claims", [
    {"exp": int(time.time()) - 60},
    {"exp": None},
    {"aud": "anon"},
    {"aud": None},
    {"iss": "https://other-ref.supabase.co/auth/v1"},
    {"sub": None},
    {"sub": "not-a-uuid"},
    {"sub": 123},  # PyJWT rejects a sub that isn't a string
])
def test_token_with_bad_claims_is_401(client, signing_key, claims):
    response = client.get("/api/me", headers=bearer(make_token(signing_key, **claims)))
    assert response.status_code == 401


@pytest.mark.usefixtures("jwks")
def test_token_signed_with_another_key_is_401(client):
    other_key = ec.generate_private_key(ec.SECP256R1())
    assert client.get("/api/me", headers=bearer(make_token(other_key))).status_code == 401


@pytest.mark.usefixtures("jwks")
def test_unknown_key_id_is_401_not_503(client, signing_key):
    token = make_token(signing_key, headers={"kid": "forged"})
    assert client.get("/api/me", headers=bearer(token)).status_code == 401


@pytest.mark.usefixtures("jwks")
def test_legacy_shared_secret_token_is_401(client):
    # Supabase's old HS256 tokens, and anything forged with a guessed secret.
    token = make_token("a-shared-secret-of-at-least-32-bytes!", algorithm="HS256")
    assert client.get("/api/me", headers=bearer(token)).status_code == 401


@pytest.mark.parametrize("error", [
    jwt.PyJWKClientConnectionError("timed out"),
    jwt.PyJWKSetError("The JWK Set did not contain any usable keys"),
])
def test_unreachable_keys_are_503(client, jwks, signing_key, error, caplog):
    jwks.error = error
    response = client.get("/api/me", headers=bearer(make_token(signing_key)))
    assert response.status_code == 503
    assert response.json() == {"detail": "Sign-in is unavailable right now"}
    # The URL is logged, so a wrong SUPABASE_URL is obvious from the logs.
    assert f"from {jwks.uri}" in caplog.text


def test_without_supabase_url_account_routes_are_503(client, monkeypatch, signing_key):
    monkeypatch.setattr(auth, "jwks_client", None)
    response = client.get("/api/me", headers=bearer(make_token(signing_key)))
    assert response.status_code == 503
    assert response.headers["cache-control"] == "private, no-store"


def test_jwks_client_is_built_from_supabase_url(monkeypatch):
    # The client is built at import, so run auth.py as a fresh module.
    monkeypatch.setattr(config, "SUPABASE_URL", "https://test-ref.supabase.co")
    spec = importlib.util.spec_from_file_location("auth_under_test", auth.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.ISSUER == ISSUER
    assert module.jwks_client.uri == f"{ISSUER}/.well-known/jwks.json"
    assert module.jwks_client.timeout == auth.JWKS_TIMEOUT
    # The key set cache expires; the per-key cache wouldn't, so revoked keys would
    # keep working on a warm instance.
    assert module.jwks_client.jwk_set_cache.lifespan == 300
    assert not hasattr(module.jwks_client.get_signing_key, "cache_info")


def test_jwks_client_is_none_without_supabase_url():
    assert config.SUPABASE_URL is None  # conftest leaves it unset
    assert auth.jwks_client is None


@pytest.mark.usefixtures("jwks")
def test_fpl_routes_ignore_tokens(client):
    for headers in ({}, {"Authorization": "Bearer not-a-token"}):
        response = client.get("/api/elements", headers=headers)
        assert response.status_code == 200
        assert "private" not in response.headers.get("cache-control", "")


# --- profiles ------------------------------------------------------------------

def test_first_call_creates_the_profile_and_later_calls_return_it(seeded_session):
    user_id = uuid4()
    first = profiles.get_profile(seeded_session, user_id)
    second = profiles.get_profile(seeded_session, user_id)
    assert first == second
    assert first.id == user_id
    assert first.created_at is not None


@pytest.mark.usefixtures("jwks")
def test_database_down_is_503_and_private(signing_key):
    def failing_session():
        raise OperationalError("SELECT", {}, Exception("connection refused"))
        yield  # pylint: disable=unreachable

    app.dependency_overrides[database.get_session] = failing_session
    try:
        response = TestClient(app).get("/api/me", headers=bearer(make_token(signing_key)))
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.headers["cache-control"] == "private, no-store"


# --- caching -------------------------------------------------------------------

def is_account_path(path):
    return path == "/api/me" or path.startswith("/api/me/")


ACCOUNT_ROUTES = sorted(
    (route.path, method) for route in app.routes if is_account_path(getattr(route, "path", ""))
    for method in route.methods
)


def test_account_routes_exist():
    assert ("/api/me", "GET") in ACCOUNT_ROUTES


@pytest.mark.usefixtures("jwks")
@pytest.mark.parametrize("path, method", ACCOUNT_ROUTES)
def test_every_account_response_is_private(client, signing_key, path, method):
    # Path parameters get a placeholder: a 404 or 422 must be private too.
    url = path.replace("{", "").replace("}", "")
    for headers in ({}, bearer(make_token(signing_key))):
        response = client.request(method, url, headers=headers)
        assert response.headers["cache-control"] == "private, no-store", (path, headers)


@pytest.mark.parametrize("path", ["/api/me", "/api/me/notes", "/api/me-not-really"])
def test_private_header_covers_only_account_paths(client, path):
    response = client.get(path)  # 404 for the made-up ones
    private = response.headers.get("cache-control") == "private, no-store"
    assert private == is_account_path(path)
