"""Reading the folder tree and choosing which folder the portal shows."""

import re
from collections.abc import Mapping
from typing import Final

from pydantic import Field, TypeAdapter, ValidationError

from alexia_api.domain.errors import PortalError, SchemaDrift, sample_of
from alexia_api.domain.messages import Folder, FolderName
from alexia_api.portal import wire
from alexia_api.portal.allowlist import GET_FOLDER_TREE, SELECT_FOLDER
from alexia_api.portal.session import Tx
from alexia_api.portal.ws import call_ws

FOLDER_IDS: Final[Mapping[FolderName, wire.FolderId]] = {
    "received": "IdCarpetaRecibidos",
    "sent": "IdCarpetaEnviados",
}
_NAME_OF: Final[Mapping[str, FolderName]] = {id_: name for name, id_ in FOLDER_IDS.items()}
_LEADING_NUMBER: Final = re.compile(r"\s*([0-9]+)", re.ASCII)


class _Attribute(wire.WireModel):
    count_text: str | None = Field(default=None, alias="spanAdicionalTexto")


class _Node(wire.WireModel):
    id: str
    text: str
    attributes: list[_Attribute] | None = None


_TREE: Final = TypeAdapter(list[_Node])


def _count(node: _Node) -> int | None:
    """The number the portal prints after the folder's name, or None when it prints none."""
    if not node.attributes:
        return None
    found = _LEADING_NUMBER.match(node.attributes[0].count_text or "")
    return int(found.group(1)) if found else None


def parse_folder_tree(reply: wire.FolderTreeReply) -> tuple[Folder, ...]:
    """The folders this API serves. The portal lists drafts and personal folders too, and those
    are left out."""
    try:
        nodes = _TREE.validate_json(reply.nodes)
    except ValidationError:
        raise PortalError(SchemaDrift(where="folder tree", sample=sample_of(reply.nodes))) from None
    folders = tuple(
        Folder(name=_NAME_OF[node.id], label=node.text, count=_count(node))
        for node in nodes
        if node.id in _NAME_OF
    )
    if not folders:
        raise PortalError(SchemaDrift(where="folder tree", sample=sample_of(reply.nodes)))
    return folders


async def read_folder_tree(tx: Tx) -> tuple[Folder, ...]:
    reply = await call_ws(tx, GET_FOLDER_TREE, wire.FolderTreeParams())
    return parse_folder_tree(reply)


async def select_folder(tx: Tx, folder: FolderName) -> None:
    """Make the portal show this folder. It keeps the choice for the rest of the session."""
    await call_ws(tx, SELECT_FOLDER, wire.SelectFolderParams(folder_id=FOLDER_IDS[folder]))
