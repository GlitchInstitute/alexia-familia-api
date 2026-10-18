"""Calls to the portal's script services.

Each call is a JSON POST to `/ACWeb/WS_Data/<Service>.asmx/<Method>` and the answer comes back
inside a `{"d": ...}` envelope. Every failure the portal can produce is turned into a typed
`PortalError` here, so readers only deal with the happy shape.
"""

import json
from typing import Any, Final
from urllib.parse import quote

from pydantic import ValidationError

from alexia_api.domain.errors import (
    Denied,
    PortalError,
    PortalMaintenance,
    SchemaDrift,
    SessionExpired,
    UnexpectedReply,
    WsRejected,
    sample_of,
)
from alexia_api.portal.allowlist import WsCall, check_call
from alexia_api.portal.session import PortalRequest, Tx
from alexia_api.portal.wire import RequestModel

LOGON_PATH: Final = "/ACWeb/LogOn.aspx"
HOME_PATH: Final = "/ACWeb/paginas/Home/HomeMetro.aspx"
MAINTENANCE_STATUSES: Final = frozenset({502, 503, 504})
WS_ACCEPT: Final = "application/json, text/javascript, */*; q=0.01"


def logon_path(institution_key: str) -> str:
    return f"{LOGON_PATH}?key={quote(institution_key, safe='')}"


def looks_like_logon_page(text: str) -> bool:
    return 'id="txtUsuario"' in text or "LogOn.aspx" in text


def _check_gates(tx: Tx, call: WsCall[Any, Any]) -> None:
    if call.effect == "write" and not tx.gates.writes:
        raise PortalError(Denied(call=call.name, reason="writes_disabled"))
    if call.effect == "restore_unread" and not tx.gates.restore_unread:
        raise PortalError(Denied(call=call.name, reason="unread_restore_disabled"))


async def call_ws[P: RequestModel, R](
    tx: Tx,
    call: WsCall[P, R],
    params: P,
    *,
    referer: str | None = None,
) -> R:
    check_call(call)
    _check_gates(tx, call)

    response = await tx.request(
        PortalRequest(
            method="POST",
            path=f"/ACWeb/WS_Data/{call.service}.asmx/{call.method}",
            headers={
                "accept": WS_ACCEPT,
                "content-type": "application/json; charset=UTF-8",
                "x-requested-with": "XMLHttpRequest",
            },
            referer=referer or tx.absolute(HOME_PATH),
            body=params.model_dump_json(by_alias=True),
            follow=False,
        )
    )

    if 300 <= response.status < 400:
        expired = looks_like_logon_page(response.location or "")
        raise PortalError(
            SessionExpired() if expired else UnexpectedReply(where=f"ws:{call.name} redirect")
        )
    if response.status == 401:
        raise PortalError(SessionExpired())
    if response.status in MAINTENANCE_STATUSES:
        raise PortalError(PortalMaintenance(status=response.status))
    if response.status != 200:
        raise PortalError(WsRejected(call=call.name, status=response.status))

    text = response.text()
    try:
        payload = json.loads(text)
    except ValueError:
        if "PaginaError.aspx" in text:
            raise PortalError(WsRejected(call=call.name, status=response.status)) from None
        if looks_like_logon_page(text):
            raise PortalError(SessionExpired()) from None
        raise PortalError(UnexpectedReply(where=f"ws:{call.name} not json")) from None

    if not isinstance(payload, dict) or "d" not in payload:
        raise PortalError(UnexpectedReply(where=f"ws:{call.name} envelope"))
    body = payload["d"]
    try:
        return call.reply.validate_python(body)
    except ValidationError as error:
        raise PortalError(
            SchemaDrift(where=f"ws:{call.name} reply", sample=sample_of(json.dumps(body)))
        ) from error
