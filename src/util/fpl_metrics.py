"""Records every call to FPL's API in fpl_calls, so we can see how much traffic we
send FPL, from where, and how it answers.

fpl_client._get_json() calls record_call() once per call. Who made it comes from a
context variable: the request's route and client, set through from_request() by
the FplCallContext middleware, or the sync step's name, set with calls_from().
Endpoints and callers are templates, so no manager or user id is ever stored.
"""

import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Optional
from urllib.parse import parse_qs, urlsplit
import requests
from sqlalchemy import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from src.db.models import FplCall
from src.util import database
from src.util.config import FPL_BASE_URL, FPL_CALL_SOURCE, VERCEL_ENV

logger = logging.getLogger(__name__)


def source_of(call_source: Optional[str], vercel_env: Optional[str]) -> str:
    """Where calls come from: a job's FPL_CALL_SOURCE, else Vercel's environment."""
    vercel = {"production": "api-production", "preview": "api-preview"}
    return call_source or vercel.get(vercel_env, "local")


SOURCE = source_of(FPL_CALL_SOURCE, VERCEL_ENV)

# The request being handled (its ASGI scope and client class), or a job's caller.
_request: ContextVar[Optional[tuple[dict, str]]] = ContextVar(
    "fpl_call_request", default=None
)
_job: ContextVar[Optional[str]] = ContextVar("fpl_call_job", default=None)


@contextmanager
def from_request(scope: dict, client: str):
    """Attribute the FPL calls made inside this block to a request: its ASGI scope,
    read for the route template at call time, and its client class."""
    token = _request.set((scope, client))
    try:
        yield
    finally:
        _request.reset(token)


@contextmanager
def calls_from(job: str):
    """Attribute the FPL calls made inside this block to a job step."""
    token = _job.set(job)
    try:
        yield
    finally:
        _job.reset(token)


def _caller() -> tuple[str, Optional[str]]:
    """Who is calling: a route template and client class, or a job and None."""
    job = _job.get()
    if job:
        return job, None
    request = _request.get()
    if request is None:
        return "unknown", None
    scope, client = request
    route = scope.get("route")
    path = getattr(route, "path", None) or "unmatched"
    return f"{scope.get('method', 'GET')} {path}", client


def endpoint_of(url: str) -> tuple[str, Optional[int]]:
    """FPL's path as a template, and the gameweek it's for, if any.

    "entry/123/event/9/picks" becomes ("entry/{id}/event/{gw}/picks", 9): a number
    after "event" is a gameweek, any other number an id. The query string is
    dropped, except fixtures' ?event=, which gives the gameweek.
    """
    parts = urlsplit(url.removeprefix(FPL_BASE_URL))
    segments = [segment for segment in parts.path.split("/") if segment]
    template, event = [], None
    for index, segment in enumerate(segments):
        if not segment.isdigit():
            template.append(segment)
        elif index and segments[index - 1] == "event":
            template.append("{gw}")
            event = int(segment)
        else:
            template.append("{id}")
    query_event = parse_qs(parts.query).get("event", [""])[0]
    if query_event.isdigit():
        event = int(query_event)
    return "/".join(template), event


def record_call(
    url: str,
    called_at: datetime,
    started: float,
    outcome: str,
    response: Optional[requests.Response],
) -> None:
    """Record one call to FPL, started at time.monotonic() started. response is None
    when none came back. Never raises a database error."""
    endpoint, event = endpoint_of(url)
    caller, client = _caller()
    save(
        {
            "called_at": called_at,
            "source": SOURCE,
            "endpoint": endpoint,
            "event": event,
            "caller": caller,
            "client": client,
            "outcome": outcome,
            "status_code": None if response is None else response.status_code,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "response_bytes": None if response is None else len(response.content),
        }
    )


def save(row: dict) -> None:
    """Write the row in its own short transaction, outside any request's or sync's.
    A failed write is logged and the FPL call goes on as normal.

    A Core insert, not the ORM's: that adds RETURNING id, which needs SELECT, and the
    API's role may only insert.
    """
    try:
        with Session(database.engine) as session, session.begin():
            session.execute(insert(FplCall).values(row))
    except SQLAlchemyError as exc:
        logger.warning("Couldn't record an FPL call to %s: %s", row["endpoint"], exc)
