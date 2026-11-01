import logging
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from src.util.config import DATABASE_CONNECT_TIMEOUT, DATABASE_URL

logger = logging.getLogger(__name__)

# Creating the engine doesn't connect; connections open on first use.
# pool_pre_ping replaces connections the pooler has closed while idle.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"connect_timeout": DATABASE_CONNECT_TIMEOUT},
)


def is_database_reachable() -> bool:
    """Run SELECT 1 and report whether it worked. Never raises."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as exc:
        logger.warning("Database check failed: %s", exc)
        return False
