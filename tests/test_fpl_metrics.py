# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""fpl_calls: one row per FPL call, with who made it and how FPL answered."""

import json
import logging
from contextlib import nullcontext
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
import requests
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from src.db.models import FplCall
from src.jobs import sync_bootstrap as job
from src.util import database, fpl_client, fpl_metrics
from src.util.fpl_metrics import (
    calls_from,
    endpoint_of,
    save as real_save,
    source_of,
)
from tests.test_api_role import ROLE

BASE = fpl_client.FPL_BASE_URL


def response(status_code=200, payload=None, body=None):
    content = body if body is not None else json.dumps(payload).encode()
    result = Mock(status_code=status_code, content=content)
    if payload is None:
        result.json.side_effect = requests.exceptions.JSONDecodeError("x", "<", 0)
    else:
        result.json.return_value = payload
    if status_code >= 400:
        result.raise_for_status.side_effect = requests.exceptions.HTTPError(
            str(status_code), response=result
        )
    return result


# --- one row per call --------------------------------------------------------


@pytest.mark.parametrize(
    "result, outcome, recorded",
    [
        (response(payload={"ok": 1}), "ok", (200, 9)),
        (response(404, body=b"Not Found"), "not_found", (404, 9)),
        (response(503, body=b"Unavailable"), "http_error", (503, 11)),
        (response(body=b"<html>"), "invalid_json", (200, 6)),
        (requests.exceptions.ReadTimeout("slow"), "timeout", (None, None)),
        (requests.exceptions.ConnectionError("no"), "connection_error", (None, None)),
        (requests.exceptions.HTTPError("no response"), "http_error", (None, None)),
    ],
)
def test_every_outcome_is_recorded_once(
    monkeypatch, fpl_calls, result, outcome, recorded
):
    """recorded: the status code and response size."""
    if isinstance(result, Exception):
        get = Mock(side_effect=result)
    else:
        get = Mock(return_value=result)
    monkeypatch.setattr(fpl_client.requests, "get", get)

    with pytest.raises(Exception) if outcome != "ok" else nullcontext():
        fpl_client.fetch_manager_history(1)

    [row] = fpl_calls
    assert row["endpoint"] == "entry/{id}/history"
    assert row["outcome"] == outcome
    assert (row["status_code"], row["response_bytes"]) == recorded
    assert row["duration_ms"] >= 0
    assert row["called_at"].tzinfo is not None
    assert row["source"] == "local"


def test_the_sync_fetches_are_recorded_too(monkeypatch, fpl_calls):
    monkeypatch.setattr(
        fpl_client.requests, "get", Mock(return_value=response(payload={}))
    )
    fpl_client.fetch_bootstrap_static()
    assert [row["endpoint"] for row in fpl_calls] == ["bootstrap-static"]


# --- endpoint templates ------------------------------------------------------


@pytest.mark.parametrize(
    "url, endpoint, event",
    [
        (f"{BASE}/bootstrap-static/", "bootstrap-static", None),
        (f"{BASE}/fixtures/", "fixtures", None),
        (f"{BASE}/fixtures/?event=12", "fixtures", 12),
        (f"{BASE}/entry/123456/", "entry/{id}", None),
        (f"{BASE}/entry/123456/transfers/", "entry/{id}/transfers", None),
        (f"{BASE}/entry/123456/history/", "entry/{id}/history", None),
        (f"{BASE}/entry/123456/event/9/picks/", "entry/{id}/event/{gw}/picks", 9),
        (f"{BASE}/event/31/live/", "event/{gw}/live", 31),
        (
            f"{BASE}/leagues-classic/5508/standings/?page_standings=2",
            "leagues-classic/{id}/standings",
            None,
        ),
    ],
)
def test_endpoint_templates(url, endpoint, event):
    assert endpoint_of(url) == (endpoint, event)


# --- who called --------------------------------------------------------------


def test_a_call_outside_any_request_or_job(monkeypatch, fpl_calls):
    monkeypatch.setattr(
        fpl_client.requests, "get", Mock(return_value=response(payload={}))
    )
    fpl_client.fetch_manager(1)
    assert (fpl_calls[0]["caller"], fpl_calls[0]["client"]) == ("unknown", None)


def test_jobs_name_their_step(monkeypatch, fpl_calls):
    monkeypatch.setattr(
        fpl_client.requests, "get", Mock(return_value=response(payload={}))
    )
    with calls_from("sync_team_names"):
        fpl_client.fetch_manager(1)
    fpl_client.fetch_manager(1)

    assert [(row["caller"], row["client"]) for row in fpl_calls] == [
        ("sync_team_names", None),
        ("unknown", None),
    ]


def test_the_sync_names_each_step(monkeypatch):
    seen = {}

    def step(name):
        def run():
            # pylint: disable-next=protected-access
            seen[name] = fpl_metrics._caller()[0]
            return True

        return run

    for name in ("sync_bootstrap", "sync_event_points", "sync_team_names"):
        monkeypatch.setattr(job, name, step(name))
    monkeypatch.setattr(job, "purge_snapshots", lambda: True)

    assert job.main() == 0
    assert seen == {
        "sync_bootstrap": "sync_bootstrap",
        "sync_event_points": "sync_event_points",
        "sync_team_names": "sync_team_names",
    }


@pytest.mark.parametrize(
    "call_source, vercel_env, source",
    [
        ("sync-staging", None, "sync-staging"),
        ("sync-production", "production", "sync-production"),
        (None, "production", "api-production"),
        (None, "preview", "api-preview"),
        (None, "development", "local"),
        (None, None, "local"),
    ],
)
def test_source(call_source, vercel_env, source):
    assert source_of(call_source, vercel_env) == source


# --- saving ------------------------------------------------------------------

ROW = {
    "called_at": datetime(2026, 11, 15, 12, tzinfo=timezone.utc),
    "source": "local",
    "endpoint": "entry/{id}/history",
    "event": None,
    "caller": "GET /api/managers/{manager_id}/history",
    "client": "ios",
    "outcome": "ok",
    "status_code": 200,
    "duration_ms": 120,
    "response_bytes": 2048,
}


def test_save_writes_a_row(monkeypatch, db_session):
    monkeypatch.setattr(database, "engine", db_session.get_bind())

    real_save(ROW)

    [saved] = db_session.scalars(select(FplCall)).all()
    assert (saved.endpoint, saved.client, saved.duration_ms) == (
        "entry/{id}/history",
        "ios",
        120,
    )


def test_the_api_role_can_save_but_not_read(monkeypatch, db_session):
    db_session.execute(text(f"SET LOCAL ROLE {ROLE}"))
    monkeypatch.setattr(database, "engine", db_session.get_bind())

    real_save(ROW)

    with pytest.raises(ProgrammingError, match="permission denied"):
        db_session.scalars(select(FplCall)).all()


def test_a_failed_save_is_logged_not_raised(monkeypatch, fpl_calls, caplog):
    def unreachable(*_args, **_kwargs):
        raise OperationalError("INSERT", {}, Exception("connection refused"))

    monkeypatch.setattr(fpl_metrics, "save", real_save)
    monkeypatch.setattr(database.engine, "connect", unreachable)
    monkeypatch.setattr(
        fpl_client.requests, "get", Mock(return_value=response(payload={"a": 1}))
    )

    with caplog.at_level(logging.WARNING):
        assert fpl_client.fetch_manager(1) == {"a": 1}
    assert "Couldn't record an FPL call to entry/{id}" in caplog.text
    assert not fpl_calls
