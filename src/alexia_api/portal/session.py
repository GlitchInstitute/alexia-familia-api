"""A polite HTTP session with one portal.

The session owns the cookie jar, the pacing clock, and the redirect rules. It is not safe for
concurrent use. The gateway holds a lock around every recipe, because the portal keeps state per
session and two recipes in flight would trample each other.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal, Protocol
from zoneinfo import ZoneInfo

import httpx

from alexia_api.clock import Clock, SystemClock
from alexia_api.domain.errors import PortalError, Transport
from alexia_api.domain.time import DEFAULT_ZONE_NAME
from alexia_api.portal.transport import (
    DEFAULT_MAX_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    exchange,
)

MAX_HOPS: Final = 5
DEFAULT_SPACING_SECONDS: Final = 0.15
_CHARSET = re.compile(r"charset\s*=\s*[\"']?([^;\s\"']+)", re.IGNORECASE)
_UTF8: Final = {"utf-8", "utf8"}


@dataclass(frozen=True, slots=True)
class Gates:
    """Operator switches that unlock calls which change something at the portal."""

    writes: bool = False
    restore_unread: bool = False
    forms: bool = False


@dataclass(frozen=True, slots=True)
class RequestLogEntry:
    at: datetime
    method: str
    path: str
    status: int
    milliseconds: int


@dataclass(frozen=True, slots=True)
class PortalRequest:
    method: Literal["GET", "POST"]
    path: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: str | None = None
    referer: str | None = None
    follow: bool = True
    max_bytes: int = DEFAULT_MAX_BYTES


@dataclass(frozen=True, slots=True)
class PortalResponse:
    status: int
    headers: httpx.Headers
    body: bytes
    path: str
    location: str | None

    def text(self) -> str:
        return decode_body(self.body, self.headers.get("content-type"))


class Tx(Protocol):
    """What a reader may do while it holds the session."""

    @property
    def gates(self) -> Gates: ...

    @property
    def zone(self) -> ZoneInfo:
        """The school's time zone. The portal writes its times as wall time in this zone."""

    async def request(self, request: PortalRequest) -> PortalResponse: ...

    def absolute(self, path: str) -> str: ...

    def now(self) -> datetime: ...

    def clear_cookies(self) -> None:
        """Forget the portal's session. The next request then counts as an expired session."""


def decode_body(body: bytes, content_type: str | None) -> str:
    """Decode a body with the charset it declares, UTF-8 without a byte order mark by default."""
    charset = "utf-8-sig"
    if content_type:
        declared = _CHARSET.search(content_type)
        if declared and declared.group(1).lower() not in _UTF8:
            charset = declared.group(1)
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8-sig", errors="replace")


def strip_query_values(path_and_query: str) -> str:
    """Keep the names in a query string and drop the values, so logs hold no ids."""
    path, _, query = path_and_query.partition("?")
    if not query:
        return path
    names = [pair.partition("=")[0] for pair in query.split("&")]
    return f"{path}?{'&'.join(names)}"


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
    return (url.scheme, url.host, url.port)


class PortalSession:
    def __init__(
        self,
        base_url: str,
        *,
        gates: Gates | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Clock | None = None,
        zone: ZoneInfo | None = None,
        min_spacing: float = DEFAULT_SPACING_SECONDS,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        on_request: Callable[[RequestLogEntry], None] | None = None,
    ) -> None:
        base = httpx.URL(base_url)
        if base.scheme not in {"http", "https"} or not base.host:
            raise ValueError("the portal address must start with http:// or https://")
        self._root = httpx.URL(f"{base.scheme}://{base.netloc.decode('ascii')}/")
        self._gates = gates or Gates()
        self._clock = clock or SystemClock()
        self._zone = zone or ZoneInfo(DEFAULT_ZONE_NAME)
        self._min_spacing = min_spacing
        self._on_request = on_request
        self._last_start = float("-inf")
        self._client = httpx.AsyncClient(
            transport=transport,
            headers={"user-agent": user_agent},
            timeout=timeout,
            follow_redirects=False,
        )

    @property
    def gates(self) -> Gates:
        return self._gates

    @property
    def zone(self) -> ZoneInfo:
        return self._zone

    @property
    def host(self) -> str:
        return self._root.host

    def absolute(self, path: str) -> str:
        return str(self._root.join(path))

    def now(self) -> datetime:
        return self._clock.now()

    def clear_cookies(self) -> None:
        self._client.cookies.clear()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, request: PortalRequest) -> PortalResponse:
        method = request.method
        content = request.body.encode("utf-8") if request.body is not None else None
        url = httpx.URL(self.absolute(request.path))
        if _origin(url) != _origin(self._root):
            raise PortalError(Transport(reason="blocked"))

        hop = 0
        while True:
            await self._pace()
            started = self._clock.monotonic()
            headers = dict(request.headers)
            if request.referer:
                headers["referer"] = request.referer
            try:
                raw = await exchange(
                    self._client,
                    method,
                    str(url),
                    headers=headers,
                    content=content,
                    max_bytes=request.max_bytes,
                )
            except PortalError:
                self._log(method, url, 0, started)
                raise
            self._log(method, url, raw.status, started)

            location = raw.headers.get("location")
            redirected = 300 <= raw.status < 400 and location is not None
            if not redirected:
                return self._response(raw.status, raw.headers, raw.body, url, None)
            if not request.follow:
                return self._response(raw.status, raw.headers, raw.body, url, location)
            if hop >= MAX_HOPS:
                raise PortalError(Transport(reason="redirect"))
            following = url.join(location or "")
            if _origin(following) != _origin(self._root):
                raise PortalError(Transport(reason="blocked"))
            if raw.status not in {307, 308}:
                method = "GET"
                content = None
            url = following
            hop += 1

    async def _pace(self) -> None:
        wait = self._last_start + self._min_spacing - self._clock.monotonic()
        if wait > 0:
            await self._clock.sleep(wait)
        self._last_start = self._clock.monotonic()

    def _log(self, method: str, url: httpx.URL, status: int, started: float) -> None:
        if self._on_request is None:
            return
        elapsed = self._clock.monotonic() - started
        self._on_request(
            RequestLogEntry(
                at=self._clock.now(),
                method=method,
                path=strip_query_values(url.raw_path.decode("ascii")),
                status=status,
                milliseconds=round(elapsed * 1000),
            )
        )

    @staticmethod
    def _response(
        status: int,
        headers: httpx.Headers,
        body: bytes,
        url: httpx.URL,
        location: str | None,
    ) -> PortalResponse:
        return PortalResponse(
            status=status,
            headers=headers,
            body=body,
            path=url.raw_path.decode("ascii"),
            location=location,
        )
