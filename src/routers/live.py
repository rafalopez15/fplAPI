"""Routes that call FPL live: FPL's answer, or the last good copy while FPL is down."""

from dataclasses import dataclass
from typing import Annotated, Any, Callable, TypeVar
from fastapi import Depends, Response
from sqlalchemy.orm import Session
from src.services import snapshots
from src.util.database import get_session
from src.util.fpl_client import FplUnavailableError

T = TypeVar("T")

# Short, so fresh data comes back soon after FPL does.
STALE_CACHE = "s-maxage=30"


@dataclass(frozen=True)
class LiveRoute:
    """A live route's response type, its cache header, and which answers to save.

    keep limits what's saved, since anyone can call these routes: rows for answers
    no client loads, like empty pages, would only fill the table.
    """

    kind: Any
    cache: str
    keep: Callable[[Any], bool] = lambda _result: True


class LiveOrSaved:
    """Saves each answer from FPL, and serves the saved one when FPL can't be
    reached, marked with X-Data-Stale-As-Of (when it was fetched).

    A plain session, not DataSession: these routes don't depend on the sync.
    """

    def __init__(
        self, response: Response, session: Annotated[Session, Depends(get_session)]
    ):
        self.response = response
        self.session = session

    def call(self, key: str, route: LiveRoute, fetch: Callable[[], T]) -> T:
        """Return fetch(), saved under key if route keeps it.

        FplNotFoundError isn't caught, so a 404 is never served from a snapshot.
        Without a snapshot, FplUnavailableError goes on to main.py's 503.
        """
        try:
            result = fetch()
        except FplUnavailableError:
            saved = snapshots.load(self.session, key, route.kind)
            if saved is None:
                raise
            result, fetched_at = saved
            self.response.headers["Cache-Control"] = STALE_CACHE
            self.response.headers["X-Data-Stale-As-Of"] = fetched_at.isoformat()
            return result
        if result is not None and route.keep(result):
            snapshots.save(self.session, key, result, route.kind)
        self.response.headers["Cache-Control"] = route.cache
        return result


Live = Annotated[LiveOrSaved, Depends()]
