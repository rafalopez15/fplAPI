"""Routes that call FPL live: FPL's answer, or the last good copy while FPL is down."""

from typing import Annotated, Any, Callable, TypeVar
from fastapi import Depends, Response
from sqlalchemy.orm import Session
from src.services import snapshots
from src.util.database import get_session
from src.util.fpl_client import FplUnavailableError

T = TypeVar("T")

# Short, so fresh data comes back soon after FPL does.
STALE_CACHE = "s-maxage=30"


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

    def call(self, key: str, kind: Any, cache: str, fetch: Callable[[], T]) -> T:
        """Return fetch(), a kind, saved under key and cached for cache.

        FplNotFoundError isn't caught, so a 404 is never served from a snapshot.
        Without a snapshot, FplUnavailableError goes on to main.py's 503.
        """
        try:
            result = fetch()
        except FplUnavailableError:
            saved = snapshots.load(self.session, key, kind)
            if saved is None:
                raise
            result, fetched_at = saved
            self.response.headers["Cache-Control"] = STALE_CACHE
            self.response.headers["X-Data-Stale-As-Of"] = fetched_at.isoformat()
            return result
        if result is not None:
            snapshots.save(self.session, key, result, kind)
        self.response.headers["Cache-Control"] = cache
        return result


Live = Annotated[LiveOrSaved, Depends()]
