import logging
import requests
from src.util.config import FPL_BASE_URL, FPL_PROXY_TIMEOUT, FPL_REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

# FPL's endpoints. They're part of FPL's API and the same in every environment,
# so they're constants rather than settings.
BOOTSTRAP_STATIC_URL = f"{FPL_BASE_URL}/bootstrap-static/"
FIXTURES_URL = f"{FPL_BASE_URL}/fixtures/"
# Manager endpoints: ENTRY_URL + "{id}/", "{id}/transfers/" or "{id}/history/".
ENTRY_URL = f"{FPL_BASE_URL}/entry/"

# Identifies us to FPL instead of the default "python-requests/x.y".
HEADERS = {"User-Agent": "fplAPI/1.0 (+https://github.com/rafalopez15/fplAPI)"}


class FplNotFoundError(Exception):
    """FPL answered 404: the manager (or other resource) doesn't exist."""


class FplUnavailableError(Exception):
    """FPL couldn't be reached or answered with an error, e.g. during its updates."""


def _get_json(url: str, timeout: float = FPL_REQUEST_TIMEOUT):
    """GET an FPL endpoint and return the parsed JSON.

    Blocking. Raises requests.exceptions.RequestException on network errors,
    timeouts, error statuses and invalid JSON.
    """
    response = requests.get(url, timeout=timeout, headers=HEADERS)
    response.raise_for_status()
    data = response.json()
    logger.info("FPL response from %s: %s", url, response.status_code)
    return data


def fetch_bootstrap_static() -> dict:
    """Fetch bootstrap-static: teams, positions, players and gameweeks. Used by the sync job."""
    return _get_json(BOOTSTRAP_STATIC_URL)


def fetch_fixtures() -> list:
    """Fetch every fixture of the season, finished or not. Used by the sync job."""
    return _get_json(FIXTURES_URL)


def _get_manager_json(path: str):
    """GET a manager endpoint for the API, which calls these live per request.

    Raises FplNotFoundError for FPL's 404 and FplUnavailableError for anything
    else that goes wrong: timeouts, connection errors, 5xx and 429 responses, and
    FPL's HTML "the game is being updated" page, which isn't JSON.
    """
    url = ENTRY_URL + path
    try:
        return _get_json(url, timeout=FPL_PROXY_TIMEOUT)
    except requests.exceptions.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            raise FplNotFoundError(url) from exc
        logger.warning("FPL error for %s: %s", url, exc)
        raise FplUnavailableError(str(exc)) from exc
    except requests.exceptions.RequestException as exc:
        logger.warning("FPL request failed for %s: %s", url, exc)
        raise FplUnavailableError(str(exc)) from exc


def fetch_manager(manager_id: int) -> dict:
    """A manager's team: name, manager name, points, rank, bank and team value."""
    return _get_manager_json(f"{manager_id}/")


def fetch_manager_transfers(manager_id: int) -> list:
    """A manager's transfers this season, newest first."""
    return _get_manager_json(f"{manager_id}/transfers/")


def fetch_manager_history(manager_id: int) -> dict:
    """A manager's points and rank per gameweek, chips played and past seasons."""
    return _get_manager_json(f"{manager_id}/history/")
