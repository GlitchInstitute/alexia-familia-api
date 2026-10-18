"""Request ids, safe response headers, and one log line per request.

The log line names the route template and not the path, so a child's name or a student id in a
URL never reaches a log. It holds the method, the template, the status, the time taken, the
request id, and the account and key names, which an operator chose and which are safe to log.
"""

import logging
import re
import time
import uuid
from collections.abc import Collection
from typing import Final

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

access_log = logging.getLogger("alexia_api.access")

REQUEST_ID_HEADER: Final = "x-request-id"
UNMATCHED_ROUTE: Final = "unmatched"
API_CONTENT_SECURITY_POLICY: Final = "default-src 'none'; frame-ancestors 'none'"
_ACCEPTED_REQUEST_ID: Final = re.compile(r"[A-Za-z0-9._~-]{8,64}")


def protective_headers(*, page: bool = False) -> dict[str, str]:
    """The headers every response carries, so that no answer is stored or sniffed as another type.

    A documentation page loads scripts, so it gets no content security policy.
    """
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }
    if not page:
        headers["Content-Security-Policy"] = API_CONTENT_SECURITY_POLICY
    return headers


def request_id_from(headers: Headers) -> str:
    """Keep the id a proxy sent when it is plain and short, and make a new one otherwise."""
    sent = headers.get(REQUEST_ID_HEADER, "")
    if _ACCEPTED_REQUEST_ID.fullmatch(sent):
        return sent
    return uuid.uuid4().hex


class RequestContext:
    """Gives each request an id and each response safe headers, and logs the request.

    `page_paths` are the documentation pages. They load scripts, so the policy that forbids
    everything but data is left off them.
    """

    def __init__(self, app: ASGIApp, *, page_paths: Collection[str] = ()) -> None:
        self.app = app
        self._page_paths = frozenset(page_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = request_id_from(Headers(scope=scope))
        scope.setdefault("state", {})["request_id"] = request_id
        is_page = scope["path"] in self._page_paths
        started = time.perf_counter()
        status = 500

        async def send_with_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-Id"] = request_id
                for name, value in protective_headers(page=is_page).items():
                    headers.setdefault(name, value)
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            self._log(scope, request_id, status, started)

    @staticmethod
    def _log(scope: Scope, request_id: str, status: int, started: float) -> None:
        route = getattr(scope.get("route"), "path", None) or UNMATCHED_ROUTE
        milliseconds = round((time.perf_counter() - started) * 1000)
        access_log.info(
            "%s %s %d %dms",
            scope["method"],
            route,
            status,
            milliseconds,
            extra={
                "request_id": request_id,
                "account": scope.get("path_params", {}).get("account"),
                "key": scope.get("state", {}).get("key_name"),
            },
        )
