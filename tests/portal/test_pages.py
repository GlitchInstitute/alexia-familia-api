"""Page fetches map every unusual answer to a typed error and never follow redirects."""

from collections.abc import Callable
from contextlib import aclosing
from typing import Any

import httpx
import pytest

from alexia_api.clock import ManualClock
from alexia_api.domain.errors import (
    PortalError,
    PortalMaintenance,
    SessionExpired,
    UnexpectedReply,
)
from alexia_api.portal.pages import FEED_ACCEPT, PAGE_ACCEPT, PageRequest, get_page
from alexia_api.portal.session import PortalResponse, PortalSession

BASE = "https://portal.test"
REQUEST = PageRequest(
    name="inbox",
    path="/ACWeb/paginas/Mensajes/Bandeja.aspx",
    referer=f"{BASE}/ACWeb/paginas/Home/HomeMetro.aspx",
    accept=PAGE_ACCEPT,
)

type Handler = Callable[[httpx.Request], httpx.Response]


async def fetch(handler: Handler, request: PageRequest = REQUEST) -> PortalResponse:
    session = PortalSession(BASE, transport=httpx.MockTransport(handler), clock=ManualClock())
    async with aclosing(session):
        return await get_page(session, request)


async def failure_of(handler: Handler) -> Any:
    with pytest.raises(PortalError) as raised:
        await fetch(handler)
    return raised.value.detail


async def test_returns_the_page_and_sends_the_expected_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="<html>inbox</html>")

    response = await fetch(handler)

    assert response.text() == "<html>inbox</html>"
    [request] = seen
    assert request.method == "GET"
    assert request.headers["accept"] == PAGE_ACCEPT
    assert request.headers["referer"] == REQUEST.referer
    assert "x-requested-with" not in request.headers


async def test_a_feed_request_says_it_is_an_xhr() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="[]")

    feed = PageRequest(
        name="agenda", path="/feed", referer=REQUEST.referer, accept=FEED_ACCEPT, xhr=True
    )
    await fetch(handler, feed)

    assert seen[0].headers["x-requested-with"] == "XMLHttpRequest"
    assert seen[0].headers["accept"] == FEED_ACCEPT


async def test_a_redirect_to_the_logon_page_means_the_session_expired() -> None:
    location = "/ACWeb/LogOn.aspx?ReturnUrl=%2f"

    detail = await failure_of(lambda _request: httpx.Response(302, headers={"location": location}))

    assert detail == SessionExpired()


async def test_a_redirect_elsewhere_is_unexpected() -> None:
    detail = await failure_of(
        lambda _request: httpx.Response(302, headers={"location": "/elsewhere"})
    )

    assert detail == UnexpectedReply(where="page:inbox redirect")


async def test_a_401_means_the_session_expired() -> None:
    assert await failure_of(lambda _request: httpx.Response(401)) == SessionExpired()


@pytest.mark.parametrize("status", [502, 503, 504])
async def test_gateway_statuses_mean_maintenance(status: int) -> None:
    detail = await failure_of(lambda _request: httpx.Response(status))

    assert detail == PortalMaintenance(status=status)


@pytest.mark.parametrize("status", [400, 403, 404, 500])
async def test_other_statuses_are_unexpected(status: int) -> None:
    detail = await failure_of(lambda _request: httpx.Response(status))

    assert detail == UnexpectedReply(where=f"page:inbox HTTP {status}")
