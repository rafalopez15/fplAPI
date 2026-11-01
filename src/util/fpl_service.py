import logging
import requests
from src.util.config import FPL_BOOTSTRAP_STATIC_URL

logger = logging.getLogger(__name__)


class FplService:
    instance = None

    def __new__(cls):
        if not cls.instance:
            cls.instance = super().__new__(cls)
            cls.fpl_data = None
        return cls.instance

    async def get_fpl_api_data(self):
        try:
            response = requests.get(FPL_BOOTSTRAP_STATIC_URL)
            if response.ok:
                self.fpl_data = response.json()
                logger.info("FPL data response: ", response.status_code)
            else:
                logger.error("Failed to fetch FPL data: ", response.text)
        except requests.exceptions.HTTPError as e:
            logger.error("Failed to fetch FPL data: ", e.response.text)
            raise SystemExit(e.response.text)
