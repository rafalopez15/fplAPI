import os
from dotenv import load_dotenv

load_dotenv()


def _get_env(key: str) -> str:
    """Return a required environment variable.

    Raises RuntimeError if it's unset or empty, so a missing .env entry stops the
    app at import time instead of turning into a broken URL later.
    """
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


FPL_BASE_URL = _get_env("FPL_BASE_URL").rstrip("/")
FPL_BOOTSTRAP_STATIC_URL = FPL_BASE_URL + _get_env("FPL_BOOTSTRAP_STATIC_PATH")
FPL_REQUEST_TIMEOUT = float(os.getenv("FPL_REQUEST_TIMEOUT", "10"))
DATABASE_URL = _get_env("DATABASE_URL")
DATABASE_CONNECT_TIMEOUT = int(os.getenv("DATABASE_CONNECT_TIMEOUT", "5"))
