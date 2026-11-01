import asyncio
import logging
import requests
from src.util.config import FPL_BOOTSTRAP_STATIC_URL, FPL_REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


class FplDataUnavailableError(Exception):
    """Raised when FPL data is read before it has been fetched successfully."""


class FplService:
    instance = None

    def __new__(cls):
        if not cls.instance:
            cls.instance = super().__new__(cls)
            cls.fpl_data = None
        return cls.instance

    def get_data(self, key: str) -> list:
        if self.fpl_data is None:
            raise FplDataUnavailableError("FPL data has not been loaded")
        return self.fpl_data.get(key, [])

    async def get_fpl_api_data(self):
        try:
            # requests is blocking, so run it in a worker thread to keep the event loop free.
            response = await asyncio.to_thread(
                requests.get, FPL_BOOTSTRAP_STATIC_URL, timeout=FPL_REQUEST_TIMEOUT
            )
            response.raise_for_status()
            self.fpl_data = response.json()
            logger.info("FPL data response: %s", response.status_code)
        except requests.exceptions.RequestException as e:
            logger.error("Failed to fetch FPL data: %s", e)
