import logging
import requests
from src.util.config import FPL_BOOTSTRAP_STATIC_URL, FPL_FIXTURES_URL, FPL_REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


def _get_json(url: str):
    """GET an FPL endpoint and return the parsed JSON.

    Blocking. Raises requests.exceptions.RequestException on network errors,
    timeouts, error statuses and invalid JSON.
    """
    response = requests.get(url, timeout=FPL_REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    logger.info("FPL response from %s: %s", url, response.status_code)
    return data


def fetch_bootstrap_static() -> dict:
    """Fetch bootstrap-static: teams, positions, players and gameweeks.

    Used by the sync job; the API reads from Postgres and never calls FPL.
    """
    return _get_json(FPL_BOOTSTRAP_STATIC_URL)


def fetch_fixtures() -> list:
    """Fetch every fixture of the season, finished or not. Used by the sync job."""
    return _get_json(FPL_FIXTURES_URL)
