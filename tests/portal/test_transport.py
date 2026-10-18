import gzip
from collections.abc import AsyncIterator

import httpx
import pytest

from alexia_api.domain.errors import PortalError, Transport
from alexia_api.portal.transport import exchange

URL = "https://portal.test/x"


async def fetch(handler: httpx.MockTransport, *, max_bytes: int = 1000) -> bytes:
    async with httpx.AsyncClient(transport=handler) as client:
        raw = await exchange(client, "GET", URL, headers={}, content=None, max_bytes=max_bytes)
    return raw.body


async def test_exchange_returns_the_status_headers_and_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, headers={"x-test": "1"}, content=b"hello")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        raw = await exchange(client, "GET", URL, headers={}, content=None, max_bytes=100)

    assert (raw.status, raw.headers["x-test"], raw.body) == (201, "1", b"hello")


async def test_exchange_sends_the_method_headers_and_body_it_was_given() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await exchange(client, "POST", URL, headers={"x-a": "b"}, content=b"{}", max_bytes=10)

    assert seen[0].method == "POST"
    assert seen[0].headers["x-a"] == "b"
    assert seen[0].content == b"{}"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectTimeout("slow"), "timeout"),
        (httpx.ConnectError("down"), "network"),
        (httpx.ReadError("reset"), "network"),
    ],
)
async def test_network_failures_become_typed_errors(error: httpx.HTTPError, reason: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(PortalError) as caught:
        await fetch(httpx.MockTransport(handler))

    assert caught.value.detail == Transport(reason=reason)  # type: ignore[arg-type]


async def test_a_declared_length_over_the_limit_is_refused_before_reading() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-length": "101"}, content=b"x" * 101)

    with pytest.raises(PortalError) as caught:
        await fetch(httpx.MockTransport(handler), max_bytes=100)

    assert caught.value.detail == Transport(reason="too_large")


async def test_a_streamed_body_over_the_limit_is_cut_off() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"a" * 60
        yield b"b" * 60

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=chunks())

    with pytest.raises(PortalError) as caught:
        await fetch(httpx.MockTransport(handler), max_bytes=100)

    assert caught.value.detail == Transport(reason="too_large")


async def test_the_limit_counts_decoded_bytes_so_a_compressed_bomb_is_stopped() -> None:
    packed = gzip.compress(b"a" * 10_000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-encoding": "gzip"}, content=packed)

    with pytest.raises(PortalError) as caught:
        await fetch(httpx.MockTransport(handler), max_bytes=1000)

    assert caught.value.detail == Transport(reason="too_large")
    assert len(packed) < 1000


async def test_a_body_exactly_at_the_limit_is_accepted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 100)

    assert await fetch(httpx.MockTransport(handler), max_bytes=100) == b"x" * 100
