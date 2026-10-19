"""The mail of the simulated families, and the way the portal words it.

Like the rest of the simulator this repeats the portal's names as literals and imports nothing
from `alexia_api.portal`. The people, the subjects, and the texts are all invented.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from typing import Final, Literal

SimFolder = Literal["received", "sent"]

FOLDER_ID_OF: Final[Mapping[SimFolder, str]] = {
    "received": "IdCarpetaRecibidos",
    "sent": "IdCarpetaEnviados",
}
FOLDER_OF_ID: Final[Mapping[str, SimFolder]] = {id_: name for name, id_ in FOLDER_ID_OF.items()}

ICON_BASE: Final = "https://static.sim.invalid/img/comunicacion"

_READ_ICONS: Final[Mapping[bool | None, tuple[str, str]]] = {
    True: ("sobre_abierto", "Leído"),
    False: ("sobre_cerrado", "No leído"),
    None: ("sobre_nuevo", "Pendiente"),
}
_TREE_TYPE: Final = "NodoArbolAttrSpanAdicionalTexto:#CospaAgilmic.NS.Web.Componentes.Tree"
_HTML_SAFE: Final = str.maketrans({"<": "\\u003c", ">": "\\u003e", "&": "\\u0026", "'": "\\u0027"})


@dataclass(frozen=True, slots=True)
class SimFile:
    """A file attached to a message. The portal serves every one of them as a plain byte stream."""

    id: str
    name: str
    data: bytes


@dataclass(frozen=True, slots=True)
class SimTranslation:
    subject: str
    body_html: str


@dataclass(frozen=True, slots=True)
class SimMessage:
    guid: str
    folder: SimFolder
    sender: str
    subject: str
    date: str
    time: str
    body_html: str
    read: bool | None = True
    expires: str | None = None
    category: str = ""
    institutional: bool = False
    anonymous: bool = False
    files: tuple[SimFile, ...] = ()
    child_names: str = ""
    can_reply: bool = True
    translations: tuple[SimTranslation, ...] = ()


def newest_first(message: SimMessage) -> tuple[str, str]:
    return (message.date, message.time)


def list_date(iso: str) -> str:
    year, month, day = iso.split("-")
    return f"{day}/{month}/{year}"


def html_safe_json(value: object) -> str:
    """JSON the way the portal writes it, with the characters that HTML cares about escaped."""
    return json.dumps(value, ensure_ascii=False).translate(_HTML_SAFE)


def feed_cells(message: SimMessage) -> list[str]:
    """The eleven cells of one row of the message list."""
    icon, state = _READ_ICONS[message.read]
    more = "Pulse para obtener más información"
    info = (
        f'<img src="{ICON_BASE}/lector.png" alt="{more}" title="{more}" '
        f'onclick="InfoLectoresComunicado(event, &quot;{message.guid}&quot;, this)" />'
    )
    names = escape(", ".join(file.name for file in message.files))
    attached = (
        f'<img src="{ICON_BASE}/attach.png" alt="Documentos adjuntos: {names}" '
        f'title="Documentos adjuntos: {names}" />'
        if message.files
        else ""
    )
    return [
        message.guid,
        f'<img src="{ICON_BASE}/{icon}.png" alt="{state}" title="{state}" />',
        "TRUE" if message.institutional else "FALSE",
        info,
        escape(message.sender),
        escape(message.subject),
        list_date(message.date),
        list_date(message.expires) if message.expires else "&nbsp",
        "True" if message.anonymous else "False",
        escape(message.category),
        attached,
    ]


def message_dto(message: SimMessage) -> dict[str, object]:
    """The reply to the call that gives the data of the open message, with every field it has."""
    spare = SimTranslation("", "")
    second, third = (*message.translations, spare, spare)[:2]
    return {
        "Destinatarios": [],
        "AdjuntosExistentes": [
            {"Id": file.id, "Nombre": file.name, "Tamanio": len(file.data)}
            for file in message.files
        ],
        "EnviarComoCentro": message.institutional,
        "Contestable": message.can_reply,
        "Asunto_1": message.subject,
        "Asunto_2": second.subject,
        "Asunto_3": third.subject,
        "Mensaje_1": message.body_html,
        "Mensaje_2": second.body_html,
        "Mensaje_3": third.body_html,
        "FechaPublicacion": message.date,
        "HoraPublicacion": message.time,
        "FechaExpiracion": message.expires or "",
        "Categoria": message.category,
        "HoyEsNoticia": False,
        "Simultaneo": False,
        "CuentaEmailId": "",
        "NombreEmisor": "" if message.anonymous else message.sender,
        "NombreHijos": message.child_names,
    }


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
