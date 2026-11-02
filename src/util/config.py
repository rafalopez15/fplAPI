import os
from dotenv import load_dotenv

load_dotenv()


def _get_env(key: str) -> str:
    """Return a required environment variable.

    Raises RuntimeError if it's unset or empty, so a missing .env entry stops the
    app at import time instead of turning into a broken URL later. Surrounding
    whitespace is stripped: Docker's --env-file and pasted secrets keep it, unlike
    python-dotenv.
    """
    value = (os.getenv(key) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


FPL_BASE_URL = _get_env("FPL_BASE_URL").rstrip("/")
FPL_BOOTSTRAP_STATIC_URL = FPL_BASE_URL + _get_env("FPL_BOOTSTRAP_STATIC_PATH")
# Optional with a default: only the sync job calls FPL, and a new required
# setting would stop the deployed API from starting until it was added there too.
FPL_FIXTURES_URL = FPL_BASE_URL + os.getenv("FPL_FIXTURES_PATH", "/fixtures/")
# Manager endpoints: FPL_ENTRY_URL + "{id}/", "{id}/transfers/" or "{id}/history/".
FPL_ENTRY_URL = FPL_BASE_URL + os.getenv("FPL_ENTRY_PATH", "/entry/")
FPL_REQUEST_TIMEOUT = float(os.getenv("FPL_REQUEST_TIMEOUT", "10"))
# Shorter than the sync's timeout: someone in the app is waiting on these calls.
FPL_PROXY_TIMEOUT = float(os.getenv("FPL_PROXY_TIMEOUT", "5"))
DATABASE_URL = _get_env("DATABASE_URL")
DATABASE_CONNECT_TIMEOUT = int(os.getenv("DATABASE_CONNECT_TIMEOUT", "5"))
# Connections kept open per process, plus extra ones allowed under load. Small,
# because every serverless instance has its own pool and Supabase's free pooler
# allows only a few connections in total.
DATABASE_POOL_SIZE = int(os.getenv("DATABASE_POOL_SIZE", "3"))
DATABASE_MAX_OVERFLOW = int(os.getenv("DATABASE_MAX_OVERFLOW", "2"))
