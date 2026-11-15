# pytest fixtures are injected as same-named arguments.
# pylint: disable=redefined-outer-name
"""fpl_calls: one row per FPL call, with who made it and how FPL answered."""

import json
import logging
import re
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
    client_of,
    endpoint_of,
    save as real_save,
    source_of,
)
from tests.conftest import (
    make_fixture,
    make_fpl_event_live,
    make_fpl_history,
    make_fpl_league_standings,
    make_fpl_manager,
    make_fpl_picks,
    make_fpl_transfers,
)
from tests.test_api_role import ROLE

BASE = fpl_client.FPL_BASE_URL

PAYLOADS = {
    "entry/{id}": make_fpl_manager,
    "entry/{id}/transfers": make_fpl_transfers,
    "entry/{id}/history": make_fpl_history,
    "entry/{id}/event/{gw}/picks": make_fpl_picks,
    "event/{gw}/live": make_fpl_event_live,
    "fixtures": lambda: [make_fixture(started=True)],
    "leagues-classic/{id}/standings": make_fpl_league_standings,
}


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


@pytest.fixture
def fpl(monkeypatch):
    """Answer every FPL URL with its conftest payload."""

    def get(url, **_kwargs):
        endpoint, _ = endpoint_of(url)
        return response(payload=PAYLOADS[endpoint]())

    monkeypatch.setattr(fpl_client.requests, "get", get)


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


@pytest.mark.parametrize(
    "user_agent, client",
    [
        ("FPL/42 CFNetwork/1568.100.1 Darwin/24.0.0", "ios"),
        ("fpl-social-smoke-test", "smoke-test"),
        ("curl/8.7.1 fpl-social-contract", "contract"),
        ("Mozilla/5.0 (Macintosh)", "other"),
        ("", "other"),
    ],
)
def test_client_from_user_agent(user_agent, client):
    assert client_of(user_agent) == client


ROUTE_CALLS = [
    (
        "/api/managers/7700093",
        "GET /api/managers/{manager_id}",
        [("entry/{id}", None)],
    ),
    (
        "/api/managers/7700093/transfers",
        "GET /api/managers/{manager_id}/transfers",
        [("entry/{id}/transfers", None), ("entry/{id}/history", None)],
    ),
    (
        "/api/managers/7700093/picks",
        "GET /api/managers/{manager_id}/picks",
        [("entry/{id}", None), ("entry/{id}/event/{gw}/picks", 9)],
    ),
    ("/api/events/9/live", "GET /api/events/{event_id}/live", [("event/{gw}/live", 9)]),
    (
        "/api/events/9/fixtures",
        "GET /api/events/{event_id}/fixtures",
        [("fixtures", 9)],
    ),
    (
        "/api/leagues/5508",
        "GET /api/leagues/{league_id}",
        [("leagues-classic/{id}/standings", None)],
    ),
]


@pytest.mark.usefixtures("fpl")
@pytest.mark.parametrize("path, caller, calls", ROUTE_CALLS)
def test_routes_record_their_template_and_client(
    client, fpl_calls, path, caller, calls
):
    response_ = client.get(path, headers={"User-Agent": "FPL/42 CFNetwork"})

    assert response_.status_code == 200
    assert [(row["endpoint"], row["event"]) for row in fpl_calls] == calls
    for row in fpl_calls:
        assert (row["caller"], row["client"]) == (caller, "ios")
        # No id from the request path, or any other number, is stored.
        assert not re.search(r"\d", row["endpoint"] + row["caller"])


@pytest.mark.usefixtures("fpl")
def test_account_routes_record_their_template(client, fpl_calls, signed_in):
    client.headers.update(signed_in())
    client.get("/api/me")
    response_ = client.put("/api/me/teams/7700093", json={"relation": "following"})

    assert response_.status_code == 200
    assert [(row["caller"], row["client"]) for row in fpl_calls] == [
        ("PUT /api/me/teams/{manager_id}", "other")
    ]


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
