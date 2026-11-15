"""Makes the request being handled known to fpl_metrics, so the FPL calls it makes
are recorded with its route and client."""

import re
from src.util import fpl_metrics

# User-Agent markers, checked in order. Anything else is "other".
CLIENTS = (
    (re.compile(r"^FPL/"), "ios"),
    # fpl-web sends it from its server, where Node's default would read as "other".
    (re.compile(r"fpl-social-web"), "web"),
    (re.compile(r"fpl-social-smoke-test"), "smoke-test"),
    (re.compile(r"fpl-social-contract"), "contract"),
)


def client_of(user_agent: str) -> str:
    for pattern, client in CLIENTS:
        if pattern.search(user_agent):
            return client
    return "other"


class FplCallContext:
    """ASGI middleware that sets the request's context for record_call().

    It passes on the scope itself: routing adds the matched route to the same dict
    later, so the route template is read when FPL is called.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        user_agent = headers.get(b"user-agent", b"").decode("latin-1")
        with fpl_metrics.from_request(scope, client_of(user_agent)):
            await self.app(scope, receive, send)
