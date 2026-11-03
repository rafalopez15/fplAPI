import importlib.util
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from src.db.models import SyncRun
from src.util import config, database


def test_engine_uses_database_url():
    url = database.engine.url.render_as_string(hide_password=False)
    assert url == config.DATABASE_URL


def test_engine_uses_pool_size():
    assert database.engine.pool.size() == config.DATABASE_POOL_SIZE


def test_engine_disables_prepared_statements(monkeypatch):
    # The engine is built at import, so run database.py as a fresh module with
    # create_engine mocked, leaving the real src.util.database untouched.
    create_engine_mock = MagicMock()
    monkeypatch.setattr("sqlalchemy.create_engine", create_engine_mock)
    spec = importlib.util.spec_from_file_location("database_under_test", database.__file__)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))

    connect_args = create_engine_mock.call_args.kwargs["connect_args"]
    assert connect_args["prepare_threshold"] is None


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


# --- sessions and sync state ----------------------------------------------

def test_get_session_yields_and_closes_a_session():
    sessions = database.get_session()
    session = next(sessions)
    assert isinstance(session, Session)
    assert session.get_bind() is database.engine
    sessions.close()


def test_last_successful_sync_ignores_failed_and_history_runs(db_session):
    finished = datetime(2026, 11, 2, 1, 17, tzinfo=timezone.utc)
    db_session.add_all([
        SyncRun(kind="bootstrap", status="succeeded", finished_at=finished),
        SyncRun(kind="bootstrap", status="failed",
                finished_at=datetime(2026, 11, 2, 2, 17, tzinfo=timezone.utc)),
        SyncRun(kind="history", status="succeeded",
                finished_at=datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)),
    ])
    db_session.flush()
    assert database.last_successful_sync(db_session) == finished


def test_last_successful_sync_is_none_before_any_sync(db_session):
    assert database.last_successful_sync(db_session) is None


def test_get_data_session_passes_through_after_a_sync(seeded_session):
    assert database.get_data_session(seeded_session) is seeded_session


def test_get_data_session_raises_before_the_first_sync(seeded_session):
    seeded_session.execute(delete(SyncRun))
    with pytest.raises(database.FplDataUnavailableError):
        database.get_data_session(seeded_session)


def test_get_last_sync_reads_through_last_successful_sync(monkeypatch):
    synced = datetime(2026, 11, 2, 1, 17, tzinfo=timezone.utc)
    monkeypatch.setattr(database, "last_successful_sync", lambda session: synced)
    assert database.get_last_sync() == synced


def test_get_last_sync_returns_none_when_unreachable(monkeypatch, caplog):
    monkeypatch.setattr(database, "engine", create_engine("postgresql+psycopg://x:x@localhost:1/x"))
    assert database.get_last_sync() is None
    assert "Couldn't read the last sync time" in caplog.text
