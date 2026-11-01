from unittest.mock import MagicMock

from sqlalchemy.exc import OperationalError
from src.util import config, database


def test_engine_uses_database_url():
    url = database.engine.url.render_as_string(hide_password=False)
    assert url == config.DATABASE_URL


def test_database_reachable(monkeypatch):
    connection = MagicMock()
    monkeypatch.setattr(database.engine, "connect", MagicMock(return_value=connection))

    assert database.is_database_reachable() is True
    connection.__enter__.return_value.execute.assert_called_once()


def test_database_unreachable(monkeypatch, caplog):
    error = OperationalError("SELECT 1", {}, Exception("connection refused"))
    monkeypatch.setattr(database.engine, "connect", MagicMock(side_effect=error))

    assert database.is_database_reachable() is False
    assert "Database check failed" in caplog.text
