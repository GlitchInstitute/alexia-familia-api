from contextlib import aclosing
from zoneinfo import ZoneInfo

import httpx
import pytest

from alexia_api.clock import ManualClock
from alexia_api.domain.errors import PortalError, Transport
from alexia_api.portal.session import (
    MAX_HOPS,
    PortalRequest,
    PortalSession,
    RequestLogEntry,
    decode_body,
    strip_query_values,
)
from alexia_api.portal.transport import DEFAULT_USER_AGENT

BASE = "https://portal.test"


def session_for(
    handler: httpx.MockTransport | None = None,
    *,
    clock: ManualClock | None = None,
    **options: object,
) -> PortalSession:
    transport = handler or httpx.MockTransport(lambda _request: httpx.Response(200))
    return PortalSession(BASE, transport=transport, clock=clock or ManualClock(), **options)  # type: ignore[arg-type]


async def test_requests_start_at_least_the_minimum_gap_apart() -> None:
    clock = ManualClock()
    starts: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        starts.append(clock.monotonic())
        return httpx.Response(200)

    async with aclosing(session_for(httpx.MockTransport(handler), clock=clock)) as session:
        for _ in range(3):
            await session.request(PortalRequest(method="GET", path="/x"))

    assert starts == pytest.approx([0.0, 0.15, 0.30])


async def test_a_gap_that_already_passed_is_not_waited_for_again() -> None:
    clock = ManualClock()
    starts: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        starts.append(clock.monotonic())
        return httpx.Response(200)

    async with aclosing(session_for(httpx.MockTransport(handler), clock=clock)) as session:
        await session.request(PortalRequest(method="GET", path="/x"))
        clock.advance(5)
        await session.request(PortalRequest(method="GET", path="/x"))

    assert starts == pytest.approx([0.0, 5.0])


async def test_a_same_origin_redirect_is_followed_with_a_get() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(f"{request.method} {request.url.path}")
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "/b"})
        return httpx.Response(200, content=b"done")

    async with aclosing(session_for(httpx.MockTransport(handler))) as session:
        response = await session.request(PortalRequest(method="POST", path="/a", body="payload"))

    assert methods == ["POST /a", "GET /b"]
    assert (response.status, response.body, response.path) == (200, b"done", "/b")


async def test_a_307_redirect_keeps_the_method_and_the_body() -> None:
    seen: list[tuple[str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.content))
        if request.url.path == "/a":
            return httpx.Response(307, headers={"location": "/b"})
        return httpx.Response(200)

    async with aclosing(session_for(httpx.MockTransport(handler))) as session:
        await session.request(PortalRequest(method="POST", path="/a", body="payload"))

    assert seen == [("POST", b"payload"), ("POST", b"payload")]


async def test_redirects_stop_after_the_hop_limit() -> None:
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(302, headers={"location": "/again"})

    async with aclosing(session_for(httpx.MockTransport(handler))) as session:
        with pytest.raises(PortalError) as caught:
            await session.request(PortalRequest(method="GET", path="/start"))

    assert caught.value.detail == Transport(reason="redirect")
    assert count == MAX_HOPS + 1


async def test_a_redirect_to_another_origin_is_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://elsewhere.test/x"})

    async with aclosing(session_for(httpx.MockTransport(handler))) as session:
        with pytest.raises(PortalError) as caught:
            await session.request(PortalRequest(method="GET", path="/start"))

    assert caught.value.detail == Transport(reason="blocked")


async def test_a_request_for_another_origin_never_leaves_the_process() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    async with aclosing(session_for(httpx.MockTransport(handler))) as session:
        with pytest.raises(PortalError) as caught:
            await session.request(PortalRequest(method="GET", path="https://elsewhere.test/x"))

    assert caught.value.detail == Transport(reason="blocked")
    assert not called


async def test_follow_false_hands_back_the_redirect_and_its_location() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/ACWeb/LogOn.aspx"})

    async with aclosing(session_for(httpx.MockTransport(handler))) as session:
        response = await session.request(PortalRequest(method="GET", path="/x", follow=False))

    assert (response.status, response.location) == (302, "/ACWeb/LogOn.aspx")


async def test_cookies_from_one_response_are_sent_on_the_next_request() -> None:
    cookies: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cookies.append(request.headers.get("cookie"))
        return httpx.Response(200, headers={"set-cookie": "session=abc; Path=/"})

    async with aclosing(session_for(httpx.MockTransport(handler))) as session:
        await session.request(PortalRequest(method="GET", path="/x"))
        await session.request(PortalRequest(method="GET", path="/x"))
        session.clear_cookies()
        await session.request(PortalRequest(method="GET", path="/x"))

    assert cookies == [None, "session=abc", None]


async def test_headers_referer_and_user_agent_are_sent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    async with aclosing(session_for(httpx.MockTransport(handler))) as session:
        await session.request(
            PortalRequest(
                method="GET",
                path="/x",
                headers={"accept": "text/html"},
                referer="https://portal.test/from",
            )
        )

    headers = seen[0].headers
    assert headers["accept"] == "text/html"
    assert headers["referer"] == "https://portal.test/from"
    assert headers["user-agent"] == DEFAULT_USER_AGENT


async def test_the_request_log_holds_names_but_never_query_values() -> None:
    entries: list[RequestLogEntry] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/down":
            raise httpx.ConnectError("down")
        return httpx.Response(204)

    async with aclosing(
        session_for(httpx.MockTransport(handler), on_request=entries.append)
    ) as session:
        await session.request(PortalRequest(method="GET", path="/x?student=secret&page=2"))
        with pytest.raises(PortalError):
            await session.request(PortalRequest(method="POST", path="/down"))

    assert [(entry.method, entry.path, entry.status) for entry in entries] == [
        ("GET", "/x?student&page", 204),
        ("POST", "/down", 0),
    ]


def test_a_portal_address_must_be_http_or_https() -> None:
    for address in ["portal.test", "ftp://portal.test", "file:///etc/passwd", ""]:
        with pytest.raises(ValueError, match="http"):
            PortalSession(address)


def test_the_session_reports_its_host_and_builds_absolute_addresses() -> None:
    session = PortalSession("https://portal.test:8443/ACWeb/ignored?x=1")

    assert session.host == "portal.test"
    assert session.absolute("/ACWeb/LogOn.aspx") == "https://portal.test:8443/ACWeb/LogOn.aspx"


def test_the_school_zone_is_madrid_until_the_session_is_given_another() -> None:
    assert PortalSession(BASE).zone.key == "Europe/Madrid"
    assert PortalSession(BASE, zone=ZoneInfo("Pacific/Auckland")).zone.key == "Pacific/Auckland"


@pytest.mark.parametrize(
    ("body", "content_type", "expected"),
    [
        ("café".encode(), "text/html; charset=utf-8", "café"),
        ("café".encode("latin-1"), "text/html; charset=ISO-8859-1", "café"),
        (b"\xef\xbb\xbf{}", "application/json", "{}"),
        (b"plain", None, "plain"),
        (b"plain", "text/html; charset=no-such-charset", "plain"),
        (b"bad \xff byte", "text/html", "bad \ufffd byte"),
    ],
)
def test_decode_body_follows_the_declared_charset_and_strips_a_byte_order_mark(
    body: bytes, content_type: str | None, expected: str
) -> None:
    assert decode_body(body, content_type) == expected


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("/x", "/x"),
        ("/x?a=1&b=2", "/x?a&b"),
        ("/x?flag", "/x?flag"),
        ("/x?", "/x"),
    ],
)
def test_strip_query_values_keeps_only_the_names(given: str, expected: str) -> None:
    assert strip_query_values(given) == expected
