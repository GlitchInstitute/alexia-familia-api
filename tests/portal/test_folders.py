"""Reading the folder tree, and choosing which folder the portal shows."""

import json

import pytest
from pydantic import ValidationError

from alexia_api.domain.errors import PortalError, SchemaDrift
from alexia_api.domain.messages import FOLDER_NAMES, Folder
from alexia_api.portal import wire
from alexia_api.portal.allowlist import SELECT_FOLDER
from alexia_api.portal.folders import FOLDER_IDS, parse_folder_tree, read_folder_tree, select_folder
from tests.harness import Harness

RECEIVED = "IdCarpetaRecibidos"
SENT = "IdCarpetaEnviados"


def node(id_: str, text: str, count: str | None = None) -> dict[str, object]:
    found: dict[str, object] = {"id": id_, "text": text}
    if count is not None:
        found["attributes"] = [{"spanAdicionalTexto": count}]
    return found


def reply_of(*nodes: dict[str, object]) -> wire.FolderTreeReply:
    return wire.FolderTreeReply(nodes=json.dumps(list(nodes)))


def test_keeps_the_received_and_sent_folders_in_the_order_the_portal_lists_them() -> None:
    reply = reply_of(
        node(SENT, "Enviados", "2"),
        node("IdCarpetaBorradores", "Borradores"),
        node(RECEIVED, "Recibidos", "8"),
        node("IdCarpetaPersonales", "Carpetas personales"),
    )

    assert parse_folder_tree(reply) == (
        Folder(name="sent", label="Enviados", count=2),
        Folder(name="received", label="Recibidos", count=8),
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("8", 8),
        ("0", 0),
        ("007", 7),
        (" 12 sin leer", 12),
        ("3 nuevos", 3),
        ("", None),
        ("nuevos", None),
        ("(5)", None),
        ("-4", None),
        ("٣", None),
    ],
)
def test_the_count_is_the_number_the_text_starts_with(text: str, expected: int | None) -> None:
    (folder,) = parse_folder_tree(reply_of(node(RECEIVED, "Recibidos", text)))

    assert folder.count == expected


def test_the_count_comes_from_the_first_attribute() -> None:
    twice: dict[str, object] = {
        "id": RECEIVED,
        "text": "Recibidos",
        "attributes": [{"spanAdicionalTexto": "4"}, {"spanAdicionalTexto": "9"}],
    }

    assert parse_folder_tree(reply_of(twice)) == (
        Folder(name="received", label="Recibidos", count=4),
    )


@pytest.mark.parametrize(
    "bare",
    [
        {"id": RECEIVED, "text": "Recibidos"},
        {"id": RECEIVED, "text": "Recibidos", "attributes": []},
        {"id": RECEIVED, "text": "Recibidos", "attributes": [{}]},
        {"id": RECEIVED, "text": "Recibidos", "attributes": [{"spanAdicionalTexto": None}]},
    ],
)
def test_a_folder_without_a_number_has_no_count(bare: dict[str, object]) -> None:
    assert parse_folder_tree(reply_of(bare)) == (
        Folder(name="received", label="Recibidos", count=None),
    )


def test_ignores_fields_it_does_not_know() -> None:
    crowded: dict[str, object] = {
        "id": RECEIVED,
        "text": "Recibidos",
        "state": "open",
        "attributes": [{"__type": "Node", "spanAdicionalTexto": "4", "style": "bold"}],
    }

    assert parse_folder_tree(reply_of(crowded)) == (
        Folder(name="received", label="Recibidos", count=4),
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "null",
        "{}",
        "[]",
        "[1]",
        '[{"id": "IdCarpetaRecibidos"}]',
        '[{"id": 7, "text": "Recibidos"}]',
        '[{"id": "IdCarpetaRecibidos", "text": "Recibidos", "attributes": "8"}]',
        '[{"id": "IdCarpetaBorradores", "text": "Borradores"}]',
    ],
)
def test_a_tree_that_cannot_be_used_is_schema_drift(text: str) -> None:
    with pytest.raises(PortalError) as raised:
        parse_folder_tree(wire.FolderTreeReply(nodes=text))

    assert raised.value.detail == SchemaDrift(where="folder tree", sample=text)


def test_every_folder_name_has_one_portal_id() -> None:
    assert set(FOLDER_IDS) == set(FOLDER_NAMES)
    assert len(set(FOLDER_IDS.values())) == len(FOLDER_IDS)


def test_choosing_a_folder_needs_an_object_back_and_ignores_what_is_in_it() -> None:
    assert SELECT_FOLDER.reply.validate_python({"anything": 1}) == {"anything": 1}
    with pytest.raises(ValidationError):
        SELECT_FOLDER.reply.validate_python("Referencia a objeto no establecida")


@pytest.mark.parametrize(
    ("username", "password", "received", "sent"),
    [("marta.ejemplo", "demo-password-a", 8, 2), ("pablo.prueba", "demo-password-b", 3, 1)],
)
async def test_reads_the_folders_the_portal_lists_for_each_family(
    harness: Harness, username: str, password: str, received: int, sent: int
) -> None:
    gateway = harness.gateway(credentials=harness.credentials(username, password))

    folders = await gateway.call(read_folder_tree)

    assert folders == (
        Folder(name="received", label="Recibidos", count=received),
        Folder(name="sent", label="Enviados", count=sent),
    )


async def test_choosing_a_folder_makes_the_portal_show_it(harness: Harness) -> None:
    gateway = harness.gateway()

    await gateway.call(lambda tx: select_folder(tx, "sent"))
    assert [session.folder for session in harness.sim.sessions.values()] == ["sent"]

    await gateway.call(lambda tx: select_folder(tx, "received"))
    assert [session.folder for session in harness.sim.sessions.values()] == ["received"]
