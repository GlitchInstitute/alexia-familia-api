"""Every portal call the server may make, as one table.

A call that is not in this table cannot leave the process. Each entry says what the call does to
the portal, so the session can refuse writes unless the operator switched them on. Readers cannot
build their own calls, because `check_call` compares by identity with the entries below.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from alexia_api.domain.errors import Denied, PortalError
from alexia_api.portal import wire

Effect = Literal["read", "write", "restore_unread"]

NEVER_CALL_PREFIXES: Final = ("Borrar", "Eliminar", "Delete")
NEVER_CALL_NAMES: Final = frozenset({"CarpetaBorrada", "MarcarComunicadoLeidoBadge"})


@dataclass(frozen=True, slots=True)
class WsCall[P: wire.RequestModel, R]:
    """One script service method, with the models of its parameters and its reply."""

    service: str
    method: str
    effect: Effect
    params: type[P]
    reply: TypeAdapter[R]

    @property
    def name(self) -> str:
        return f"{self.service}.{self.method}"


def _adapter[T](shape: type[T]) -> TypeAdapter[T]:
    if issubclass(shape, BaseModel):
        return TypeAdapter(shape)
    return TypeAdapter(shape, config=ConfigDict(strict=True))


VALIDAR = WsCall("WSLogOn", "Validar", "read", wire.ValidarParams, _adapter(str))
GET_ROLES = WsCall("WSLogOn", "GetRoles", "read", wire.GetRolesParams, _adapter(wire.GetRolesReply))
VALIDAR_ROL = WsCall(
    "WSLogOn", "ValidarRol", "read", wire.ValidarRolParams, _adapter(wire.ValidarRolReply)
)
CHECK_SESSION = WsCall(
    "WSSesion", "CheckSession", "read", wire.CheckSessionParams, _adapter(wire.CheckSessionReply)
)
GET_TRACKING = WsCall(
    "WSHome", "GetWPSeguimiento", "read", wire.TrackingParams, _adapter(wire.TrackingReply)
)
GET_ROSTER = WsCall(
    "WSReuniones",
    "GetEmpleadosByHijo",
    "read",
    wire.RosterParams,
    TypeAdapter(list[wire.RosterItem]),
)
GET_FOLDER_TREE = WsCall(
    "WSComunicados",
    "GetArbolCarpetasJSON",
    "read",
    wire.FolderTreeParams,
    _adapter(wire.FolderTreeReply),
)
SELECT_FOLDER = WsCall(
    "WSComunicados",
    "CarpetaSeleccionada",
    "read",
    wire.SelectFolderParams,
    TypeAdapter(dict[str, object], config=ConfigDict(strict=True)),
)
GET_MESSAGE_DATA = WsCall(
    "WSComunicados",
    "GetDatosPaginaComunicado",
    "read",
    wire.EmptyParams,
    _adapter(wire.MessageReply),
)

_ENTRIES: Final[tuple[WsCall[Any, Any], ...]] = (
    VALIDAR,
    GET_ROLES,
    VALIDAR_ROL,
    CHECK_SESSION,
    GET_TRACKING,
    GET_ROSTER,
    GET_FOLDER_TREE,
    SELECT_FOLDER,
    GET_MESSAGE_DATA,
)
ALLOWLIST: Final[Mapping[str, WsCall[Any, Any]]] = MappingProxyType(
    {call.name: call for call in _ENTRIES}
)


def is_never_call(method: str) -> bool:
    return method.startswith(NEVER_CALL_PREFIXES) or method in NEVER_CALL_NAMES


def check_call(call: WsCall[Any, Any]) -> None:
    """Refuse any call that is a never-call method or is not the exact entry in the table."""
    if is_never_call(call.method):
        raise PortalError(Denied(call=call.name, reason="never_call"))
    if ALLOWLIST.get(call.name) is not call:
        raise PortalError(Denied(call=call.name, reason="not_on_allowlist"))
