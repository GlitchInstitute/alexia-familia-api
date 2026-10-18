"""The shapes the portal's script services speak.

Field names are the portal's own, in Spanish and inconsistent about case. Each model gives them
a plain snake_case name once, here, so nothing outside `alexia_api.portal` sees them. Models are
strict about types, because a portal that starts sending a number as text should fail loudly as
`portal_changed` and not turn into wrong data.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from alexia_api.domain.ids import GUID_PATTERN, attachment_token

GuidText = Annotated[str, StringConstraints(pattern=GUID_PATTERN)]


class WireModel(BaseModel):
    """A reply from the portal. Unknown fields are ignored, wrong types are not."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore", populate_by_name=True)


class RequestModel(BaseModel):
    """The parameters of a call. Unknown fields are refused, so a typo cannot reach the portal."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", populate_by_name=True)


class EmptyParams(RequestModel):
    """For calls that take no parameters."""


class ValidarParams(RequestModel):
    token: str = Field(min_length=1)
    nickname: str = Field(min_length=1)
    password: str = Field(min_length=1)


class GetRolesParams(RequestModel):
    token: str = Field(min_length=1)


class ValidarRolParams(RequestModel):
    token: str = Field(min_length=1)
    role_id: GuidText = Field(alias="idRol")
    evaluate_multifactor: bool = Field(alias="evaluarMultifactor")


class CheckSessionParams(RequestModel):
    counter: int = Field(alias="contador", ge=0)


class TrackingParams(RequestModel):
    student_id: GuidText = Field(alias="idAlumno")


class RosterParams(RequestModel):
    student_id: GuidText = Field(alias="guidHijo")


class RoleChoice(WireModel):
    identifier: GuidText = Field(alias="Identificador")


class GetRolesReply(WireModel):
    error: str | None = Field(default=None, alias="Error")
    roles: list[RoleChoice] | None = Field(default=None, alias="OK")
    multifactor: bool | None = None
    route: str | None = Field(default=None, alias="Ruta")


class ValidarRolReply(WireModel):
    ok: bool | None = Field(default=None, alias="OK")
    home_route: str | None = Field(default=None, alias="RutaHome")
    error: str | None = Field(default=None, alias="Error")
    change_password: Any = Field(default=None, alias="CambiarPws")
    legal_text: Any = Field(default=None, alias="TxtLegales")
    account_confirmed: bool | None = Field(default=None, alias="OKCuenta")
    account_guid: str | None = Field(default=None, alias="GuidCuenta")
    online_enrollment: Any = Field(default=None, alias="MatOnline")
    show_classroom: Any = Field(default=None, alias="muetraOpClassroom")
    route: str | None = Field(default=None, alias="Ruta")


class CheckSessionReply(WireModel):
    is_ok: bool = Field(alias="IsOk")
    message: str | None = Field(default=None, alias="Mensaje")


class TrackingReply(WireModel):
    """Five HTML fragments, one per counter, each holding the number in an `<em>` tag."""

    tasks: str = Field(alias="tareas")
    activities: str = Field(alias="actividades")
    notes: str = Field(alias="anotaciones")
    tests: str = Field(alias="controles")
    incidents: str = Field(alias="incidencias")


class RosterItem(WireModel):
    value: str = Field(alias="Valor")
    text: str = Field(alias="Texto")


FolderId = Literal["IdCarpetaRecibidos", "IdCarpetaEnviados"]
MessagesFlag = Literal["0"]
"""The portal's `IsAutorizacion` flag. `0` lists messages. `1` lists authorization forms, which
the folder calls do not read."""


class FolderTreeParams(RequestModel):
    is_authorization: MessagesFlag = Field(default="0", alias="IsAutorizacion")


class FolderTreeReply(WireModel):
    """The folders, as JSON text inside the JSON reply."""

    nodes: str = Field(alias="nodos")


class SelectFolderParams(RequestModel):
    folder_id: FolderId = Field(alias="idCarpeta")
    is_authorization: MessagesFlag = Field(default="0", alias="IsAutorizacion")
    search_text: Literal[""] = Field(default="", alias="TextoBusqueda")


class MessageFile(WireModel):
    """A file that the page of a message lists."""

    id: str = Field(alias="Id")
    name: str = Field(alias="Nombre")
    size: int = Field(alias="Tamanio", ge=0)

    @field_validator("id")
    @classmethod
    def _can_be_named_by_a_token(cls, value: str) -> str:
        attachment_token(value)
        return value


class MessageReply(WireModel):
    """The page of one message. The subject and the text each come in three versions.

    The portal sends more than this, such as the recipients and the settings the sender chose.
    Nothing here uses those, so they are left out.
    """

    files: list[MessageFile] = Field(alias="AdjuntosExistentes")
    can_reply: bool = Field(alias="Contestable")
    subject_1: str = Field(alias="Asunto_1")
    subject_2: str = Field(alias="Asunto_2")
    subject_3: str = Field(alias="Asunto_3")
    text_1: str = Field(alias="Mensaje_1")
    text_2: str = Field(alias="Mensaje_2")
    text_3: str = Field(alias="Mensaje_3")
    published_on: str = Field(alias="FechaPublicacion", pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    published_at: str = Field(alias="HoraPublicacion", pattern=r"^[0-9]{2}:[0-9]{2}$")
    sender: str = Field(alias="NombreEmisor")
    child_names: str = Field(alias="NombreHijos")
