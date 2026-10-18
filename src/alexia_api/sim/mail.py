"""The mail of the simulated families, and the way the portal words it.

Like the rest of the simulator this repeats the portal's names as literals and imports nothing
from `alexia_api.portal`. The people, the subjects, and the texts are all invented.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

SimFolder = Literal["received", "sent"]

FOLDER_ID_OF: Final[Mapping[SimFolder, str]] = {
    "received": "IdCarpetaRecibidos",
    "sent": "IdCarpetaEnviados",
}
FOLDER_OF_ID: Final[Mapping[str, SimFolder]] = {id_: name for name, id_ in FOLDER_ID_OF.items()}

_TREE_TYPE: Final = "NodoArbolAttrSpanAdicionalTexto:#CospaAgilmic.NS.Web.Componentes.Tree"


@dataclass(frozen=True, slots=True)
class SimFile:
    id: str
    name: str
    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class SimMessage:
    guid: str
    folder: SimFolder
    sender: str
    subject: str
    date: str
    time: str
    body_html: str
    read: bool = True
    expires: str | None = None
    category: str = ""
    institutional: bool = False
    anonymous: bool = False
    files: tuple[SimFile, ...] = ()


def newest_first(message: SimMessage) -> tuple[str, str]:
    return (message.date, message.time)


def folder_tree(counts: Mapping[SimFolder, int], selected: SimFolder) -> dict[str, str]:
    """The reply to the folder tree call. The tree itself travels as JSON text in the reply."""

    def counted(folder: SimFolder, text: str) -> dict[str, object]:
        return {
            "attributes": [{"__type": _TREE_TYPE, "spanAdicionalTexto": str(counts[folder])}],
            "id": FOLDER_ID_OF[folder],
            "text": text,
        }

    return {
        "nodos": json.dumps(
            [
                counted("received", "Recibidos"),
                counted("sent", "Enviados"),
                {"id": "IdCarpetaBorradores", "text": "Borradores"},
                {"id": "IdCarpetaPersonales", "text": "Carpetas personales"},
            ]
        ),
        "nodosCombo": json.dumps([{"id": "IdCarpetaOriginal", "text": "Restaurar a original"}]),
        "carpeta": FOLDER_ID_OF[selected],
    }


def folder_selection(folder: SimFolder) -> dict[str, object]:
    """The reply to choosing a folder, which says which columns the list hides."""
    hidden = (
        ["Guid", "INSTITUCIONAL", "IsAnonimo", "FechaFin", "INFO_DESTS_LECTORES"]
        if folder == "received"
        else ["Guid", "INSTITUCIONAL", "NOMBRE", "ALUMNOS"]
    )
    return {
        "esCarpetaPersonal": False,
        "colsOcultar": hidden,
        "nombreColRecibidos": "FechaInicio",
        "textoColRecibidos": "Recibido" if folder == "received" else "Enviado el",
    }
