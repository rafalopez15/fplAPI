import logging
import requests
from src.util.config import FPL_BOOTSTRAP_STATIC_URL, FPL_REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


def fetch_bootstrap_static() -> dict:
    """Fetch bootstrap-static from FPL and return the parsed JSON.

    Used by the sync job; the API reads from Postgres and never calls FPL. Blocking.
    Raises requests.exceptions.RequestException on network errors, timeouts,
    error statuses and invalid JSON.
    """
    response = requests.get(FPL_BOOTSTRAP_STATIC_URL, timeout=FPL_REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    logger.info("FPL data response: %s", response.status_code)
    return data
