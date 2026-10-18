"""Script service calls turn every kind of portal answer into data or a typed error."""

import json
from collections.abc import Callable
from contextlib import aclosing
from types import MappingProxyType
from typing import Any

import httpx
import pytest
from pydantic import TypeAdapter

from alexia_api.clock import ManualClock
from alexia_api.domain.errors import (
    Denied,
    PortalError,
    PortalMaintenance,
    SchemaDrift,
    SessionExpired,
    UnexpectedReply,
    WsRejected,
)
from alexia_api.portal import allowlist, wire
from alexia_api.portal.allowlist import CHECK_SESSION, Effect, WsCall
from alexia_api.portal.session import Gates, PortalSession
from alexia_api.portal.ws import HOME_PATH, call_ws, logon_path, looks_like_logon_page

BASE = "https://portal.test"
NAME = CHECK_SESSION.name
PARAMS = wire.CheckSessionParams(counter=1)
LOGON_HTML = '<html><input id="txtUsuario" /></html>'

type Handler = Callable[[httpx.Request], httpx.Response]


def answer(body: object) -> httpx.Response:
    return httpx.Response(200, json={"d": body})


def unreachable(_request: httpx.Request) -> httpx.Response:
    raise AssertionError("the call must not reach the portal")


async def run(
    handler: Handler,
    *,
    call: WsCall[Any, Any] = CHECK_SESSION,
    params: wire.RequestModel = PARAMS,
    gates: Gates | None = None,
    referer: str | None = None,
) -> Any:
    session = PortalSession(
        BASE, transport=httpx.MockTransport(handler), clock=ManualClock(), gates=gates
    )
    async with aclosing(session):
        return await call_ws(session, call, params, referer=referer)


async def failure_of(handler: Handler, **options: Any) -> object:
    with pytest.raises(PortalError) as raised:
        await run(handler, **options)
    return raised.value.detail


def register(monkeypatch: pytest.MonkeyPatch, call: WsCall[Any, Any]) -> None:
    table = MappingProxyType({**allowlist.ALLOWLIST, call.name: call})
    monkeypatch.setattr(allowlist, "ALLOWLIST", table)


def fake(method: str, effect: Effect) -> WsCall[wire.EmptyParams, str]:
    return WsCall("WSFake", method, effect, wire.EmptyParams, TypeAdapter(str))


async def test_sends_the_documented_request_and_returns_the_typed_reply() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer({"IsOk": True, "Mensaje": None})

    reply = await run(handler)

    assert reply.is_ok is True
    [request] = seen
    assert request.method == "POST"
    assert request.url.path == "/ACWeb/WS_Data/WSSesion.asmx/CheckSession"
    assert request.headers["x-requested-with"] == "XMLHttpRequest"
    assert request.headers["content-type"] == "application/json; charset=UTF-8"
    assert request.headers["referer"] == f"{BASE}{HOME_PATH}"
    assert json.loads(request.content) == {"contador": 1}


async def test_a_caller_can_name_the_referer() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer({"IsOk": True})

    await run(handler, referer=f"{BASE}/ACWeb/LogOn.aspx")

    assert seen[0].headers["referer"] == f"{BASE}/ACWeb/LogOn.aspx"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, SessionExpired()),
        (404, WsRejected(call=NAME, status=404)),
        (500, WsRejected(call=NAME, status=500)),
        (502, PortalMaintenance(status=502)),
        (503, PortalMaintenance(status=503)),
        (504, PortalMaintenance(status=504)),
    ],
)
async def test_error_statuses_become_typed_errors(status: int, expected: object) -> None:
    detail = await failure_of(lambda _request: httpx.Response(status))

    assert detail == expected


async def test_a_redirect_to_the_logon_page_means_the_session_expired() -> None:
    location = "/ACWeb/LogOn.aspx?ReturnUrl=%2fACWeb"

    detail = await failure_of(lambda _request: httpx.Response(302, headers={"location": location}))

    assert detail == SessionExpired()


async def test_any_other_redirect_is_unexpected() -> None:
    detail = await failure_of(
        lambda _request: httpx.Response(302, headers={"location": "/somewhere/else"})
    )

    assert detail == UnexpectedReply(where=f"ws:{NAME} redirect")


async def test_a_logon_page_in_the_body_means_the_session_expired() -> None:
    detail = await failure_of(lambda _request: httpx.Response(200, text=LOGON_HTML))

    assert detail == SessionExpired()


async def test_the_error_page_the_portal_posts_to_is_a_rejection() -> None:
    page = '<form action="/ACWeb/paginas/Publicas/PaginaError.aspx"></form>'

    detail = await failure_of(lambda _request: httpx.Response(200, text=page))

    assert detail == WsRejected(call=NAME, status=200)


async def test_text_that_is_not_json_is_unexpected() -> None:
    detail = await failure_of(lambda _request: httpx.Response(200, text="hello"))

    assert detail == UnexpectedReply(where=f"ws:{NAME} not json")


@pytest.mark.parametrize("payload", [{"x": 1}, [1, 2], "text", 7])
async def test_a_reply_without_the_d_envelope_is_unexpected(payload: object) -> None:
    detail = await failure_of(lambda _request: httpx.Response(200, json=payload))

    assert detail == UnexpectedReply(where=f"ws:{NAME} envelope")


@pytest.mark.parametrize("body", [{"IsOk": "yes"}, {"Mensaje": "no flag"}, None, [1]])
async def test_a_reply_of_the_wrong_shape_is_schema_drift(body: object) -> None:
    detail = await failure_of(lambda _request: answer(body))

    assert isinstance(detail, SchemaDrift)
    assert detail.where == f"ws:{NAME} reply"
    assert detail.sample == json.dumps(body)


async def test_new_fields_in_a_reply_are_ignored() -> None:
    reply = await run(lambda _request: answer({"IsOk": True, "Brand": "new"}))

    assert reply.is_ok is True


async def test_a_write_call_is_refused_without_the_writes_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = fake("Send", "write")
    register(monkeypatch, call)

    detail = await failure_of(unreachable, call=call, params=wire.EmptyParams())

    assert detail == Denied(call=call.name, reason="writes_disabled")


async def test_a_write_call_goes_through_with_the_writes_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = fake("Send", "write")
    register(monkeypatch, call)

    reply = await run(
        lambda _request: answer("sent"),
        call=call,
        params=wire.EmptyParams(),
        gates=Gates(writes=True),
    )

    assert reply == "sent"


async def test_restoring_unread_needs_its_own_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    call = fake("Restore", "restore_unread")
    register(monkeypatch, call)

    detail = await failure_of(
        unreachable, call=call, params=wire.EmptyParams(), gates=Gates(writes=True)
    )
    reply = await run(
        lambda _request: answer("ok"),
        call=call,
        params=wire.EmptyParams(),
        gates=Gates(restore_unread=True),
    )

    assert detail == Denied(call=call.name, reason="unread_restore_disabled")
    assert reply == "ok"


async def test_a_never_call_method_is_refused_even_when_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = fake("BorrarTodo", "read")
    register(monkeypatch, call)

    detail = await failure_of(unreachable, call=call, params=wire.EmptyParams())

    assert detail == Denied(call=call.name, reason="never_call")


async def test_a_call_that_is_not_listed_is_refused() -> None:
    call = fake("Unlisted", "read")

    detail = await failure_of(unreachable, call=call, params=wire.EmptyParams())

    assert detail == Denied(call=call.name, reason="not_on_allowlist")


def test_the_logon_address_carries_the_institution_key_quoted() -> None:
    assert logon_path("my school/1") == "/ACWeb/LogOn.aspx?key=my%20school%2F1"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (LOGON_HTML, True),
        ("/ACWeb/LogOn.aspx?ReturnUrl=x", True),
        ("<html>inbox</html>", False),
        ("", False),
    ],
)
def test_it_recognises_the_logon_page(text: str, expected: bool) -> None:
    assert looks_like_logon_page(text) is expected
