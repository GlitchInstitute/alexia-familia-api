import ast
import re
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from alexia_api.domain.errors import Denied, PortalError
from alexia_api.portal import wire
from alexia_api.portal.allowlist import ALLOWLIST, WsCall, check_call, is_never_call

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "alexia_api"
PROTOCOL_NOTES = ROOT / "docs" / "protocol.md"
METHOD_NAME = re.compile(r"[A-Z][A-Za-z0-9]+")


@pytest.mark.parametrize(
    "method",
    [
        "BorrarComunicado",
        "EliminarCarpeta",
        "DeleteMessage",
        "CarpetaBorrada",
        "MarcarComunicadoLeidoBadge",
    ],
)
def test_destructive_methods_are_never_calls(method: str) -> None:
    assert is_never_call(method)


@pytest.mark.parametrize(
    "method",
    ["GetRoles", "Validar", "MarcarEstadoLectura", "Borrador", "GuardarBorradorPaginaComunicado"],
)
def test_ordinary_methods_are_not_never_calls(method: str) -> None:
    assert not is_never_call(method)


def test_every_entry_passes_the_check_and_none_is_a_never_call() -> None:
    assert ALLOWLIST
    for call in ALLOWLIST.values():
        check_call(call)
        assert not is_never_call(call.method)


def test_entries_have_unique_well_formed_names() -> None:
    names = [call.name for call in ALLOWLIST.values()]

    assert len(set(names)) == len(names)
    assert all(re.fullmatch(r"WS[A-Za-z]+\.[A-Za-z]+", name) for name in names)


def test_the_protocol_notes_have_a_row_for_every_call_on_the_allowlist() -> None:
    notes = PROTOCOL_NOTES.read_text(encoding="utf-8")

    assert [call.name for call in ALLOWLIST.values() if f"| `{call.name}` |" not in notes] == []


def test_a_lookalike_with_the_same_name_is_not_on_the_allowlist() -> None:
    lookalike = WsCall("WSLogOn", "Validar", "read", wire.ValidarParams, TypeAdapter(str))

    with pytest.raises(PortalError) as caught:
        check_call(lookalike)

    assert caught.value.detail == Denied(call="WSLogOn.Validar", reason="not_on_allowlist")


def test_a_never_call_is_refused_whatever_else_is_true_of_it() -> None:
    destructive = WsCall(
        "WSComunicados", "BorrarComunicado", "write", wire.EmptyParams, TypeAdapter(str)
    )

    with pytest.raises(PortalError) as caught:
        check_call(destructive)

    assert caught.value.detail == Denied(call="WSComunicados.BorrarComunicado", reason="never_call")


def _never_call_names_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        f"{path.name}: {node.value}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and METHOD_NAME.fullmatch(node.value)
        and is_never_call(node.value)
    ]


def test_no_source_file_outside_the_allowlist_names_a_never_call_method() -> None:
    offenders = [
        name
        for path in SOURCE.rglob("*.py")
        if path.name != "allowlist.py"
        for name in _never_call_names_in(path)
    ]

    assert offenders == []
