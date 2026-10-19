"""A fake Alexia portal, for tests and for the demo.

It speaks the shapes the real portal speaks, from the logon token to the script services, and it
serves synthetic families only. Tests and the demo drive it in process through
`PortalSim.transport()`. Faults are switches on `PortalSim.options`, so each failure path in the
client has a test that causes it on purpose.

The simulator is an independent statement of the protocol. It repeats paths and refusal texts as
literals and imports nothing from `alexia_api.portal`, so a wrong constant in the client cannot
hide behind the same constant in the fake.
"""

import json
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from html import escape
from typing import Any, Final, Literal
from urllib.parse import quote

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from alexia_api.clock import Clock, SystemClock
from alexia_api.domain.errors import Interstitial
from alexia_api.sim import agenda
from alexia_api.sim.mail import (
    FOLDER_OF_ID,
    SimFolder,
    SimMessage,
    feed_cells,
    folder_selection,
    folder_tree,
    html_safe_json,
    message_dto,
    newest_first,
)
from alexia_api.sim.world import SimChild, SimFamily, SimWorld, default_world, synthetic_guid

BASE_URL: Final = "https://sim.invalid"
LOGON_PATH: Final = "/ACWeb/LogOn.aspx"
HOME_PATH: Final = "/ACWeb/paginas/Home/HomeMetro.aspx"
MESSAGES_PATH: Final = "/ACWeb/paginas/Comunicacion/Comunicados.aspx"
MESSAGE_PATH: Final = "/ACWeb/paginas/Comunicacion/Comunicado.aspx"
REPOSITORY_PATH: Final = "/ACWeb/Controladores/ControladorRepositorio.ashx"
FEED_QUERY: Final = frozenset({"jqGridID", "_search", "nd", "rows", "page", "sidx", "sord"})
_FEED_NUMBERS: Final = ("nd", "rows", "page")
_MESSAGE_QUERY: Final = frozenset(
    {
        "GuidComunicadoOrigen",
        "TipoComunicado",
        "AccionComunicado",
        "DestsInicialesCom",
        "TxtDefaultCom",
        "AccionExtraCom",
    }
)
_DOWNLOAD_QUERY: Final = frozenset({"tipo", "nombre", "alias"})
_DOWNLOAD_FAILED_PAGE: Final = (
    "<html><head><title>Error</title></head><body>No se ha podido descargar el fichero."
    "</body></html>"
)

EXPIRED_LOGON_TEXT: Final = "La sesión ha caducado. Vuelva a iniciar sesión."
BAD_CREDENTIALS_TEXT: Final = "Usuario o código de acceso incorrecto"
LOCKED_TEXT: Final = "La cuenta está bloqueada. Contacte con el centro."
FAULT_TEXT: Final = "Referencia a objeto no establecida como instancia de un objeto."
IDLE_LIMIT_MINUTES: Final = 20
SESSION_COOKIE: Final = "AC_SessionId"

_ERROR_REDIRECT_PAGE: Final = (
    '<html><head></head><body onload="document.formRedirect.submit()"><center>'
    '<form name="formRedirect" method="post" action="/ACWeb/paginas/Publicas/PaginaError.aspx">'
    '<input name="POST_Mensaje" type="hidden" value=""/>'
    '<input name="POST_master" type="hidden" value="0"/></form></center></body></html>'
)
_AUTH_PARAMS: Final[dict[str, frozenset[str]]] = {
    "WSLogOn.Validar": frozenset({"token", "nickname", "password"}),
    "WSLogOn.GetRoles": frozenset({"token"}),
    "WSLogOn.ValidarRol": frozenset({"token", "idRol", "evaluarMultifactor"}),
    "WSSesion.CheckSession": frozenset({"contador"}),
    "WSHome.IsAppAccess": frozenset(),
}


class SimDroppedError(Exception):
    """Raised by a handler to cut the connection without an answer."""


class SimFaultError(Exception):
    """Raised by a handler to answer with the portal's generic server error."""


@dataclass(slots=True)
class SimOptions:
    """Switches that make the portal behave badly on purpose."""

    roles: int = 1
    multifactor: bool = False
    interstitial: Interstitial | None = None
    maintenance: Literal["none", "page", "http503"] = "none"
    require_referer: bool = True
    session_ttl_seconds: float = 20 * 60
    lock_after_failures: int | None = None
    home_route: str | None = None
    feed_cell_count: int | None = None
    message_time: str | None = None
    download_as_page: bool = False
    download_extra_bytes: int = 0
    """Bytes added to the end of every download, or taken off the end when negative."""
    agenda_ignores_end: bool = True
    """The real feed answers up to the end of the term, whatever end the request names."""
    agenda_standing_events: bool = True
    """The real feed sends every school event of the term, inside the range or not."""
    agenda_not_json: bool = False
    """The feed answers with the logon page, as it does when the session is gone."""
    agenda_bad_event: bool = False
    """The first entry of the feed has a start that is not a date."""
    agenda_feed_fails: bool = False
    """The feed answers with the portal's server error, as it does when it cannot build a week."""
    home_without_guardian: bool = False
    """The home page lists the children and does not list the guardian."""


@dataclass(slots=True)
class SimSession:
    id: str
    token: str = ""
    stage: Literal["anonymous", "validated", "authenticated"] = "anonymous"
    last_activity: float = 0.0
    family: SimFamily | None = None
    folder: SimFolder = "received"
    message_guid: str | None = None
    open_agenda: tuple[agenda.SimAgendaScope, str] | None = None


@dataclass(frozen=True, slots=True)
class SimRequest:
    method: str
    path: str
    status: int
    at: float
    query: str = ""


@dataclass(frozen=True, slots=True)
class Service:
    """A script service method that needs a live session, and the parameter names it expects.

    `referer` names the page the call must come from, for the methods that read the page the
    session has open.
    """

    params: frozenset[str]
    handle: Callable[[SimSession, dict[str, Any]], object]
    referer: Callable[[SimSession], str] | None = None


def _message_url(guid: str | None) -> str:
    return (
        f"{MESSAGE_PATH}?GuidComunicadoOrigen={guid}&TipoComunicado=N&AccionComunicado=1"
        "&DestsInicialesCom=&TxtDefaultCom=&AccionExtraCom="
    )


def _photo(key: str, size: int) -> str:
    return (
        "/ACWeb/controladores/ControladorFotografias.ashx"
        f"?tipo=2&amp;key={key}&amp;formato=0&amp;maxWidth={size}&amp;maxHeigth={size}"
        "&amp;default=foto_defeault_nina.svg"
    )


def render_home(family: SimFamily, *, guardian_listed: bool = True) -> str:
    tracked = "".join(
        f'<li class="{"hijo_activo" if index == 0 else ""}" '
        f'onclick="javascript:CambiarHijoSeguimiento(event);" hijo="{child.student_id}">'
        f'<a href="#"><div><span><img loading="lazy" src="{_photo(child.person_id, 100)}" '
        f'style="border-width:0px;"></span></div><p>{escape(child.full_name)}</p></a></li>'
        for index, child in enumerate(family.children)
    )
    guardian = family.guardian
    listed_guardian = (
        f'<li class="padre activo" '
        f"onclick=\"javascript:HijoClicked(this,'{guardian.person_id}', 'True');\">"
        f'<div class="contienefoto"><img src="{_photo(guardian.person_id, 49)}"></div>'
        f'<ul class="datos_user"><li><strong>Padre</strong></li>'
        f"<li><h3>{escape(guardian.first_name)}</h3></li></ul></li>"
        if guardian_listed
        else ""
    )
    picker = listed_guardian + "".join(
        f'<li class="hijo inactivo" '
        f"onclick=\"javascript:HijoClicked(this,'{child.person_id}', 'False');\">"
        f'<div class="contienefoto"><img src="{_photo(child.person_id, 49)}"></div>'
        f'<ul class="datos_user"><li><strong>{escape(child.relation)}</strong></li>'
        f"<li><h3>{escape(child.first_name)}</h3></li></ul></li>"
        for child in family.children
    )
    return (
        "<!DOCTYPE html><html><head><title>Inicio</title></head><body>"
        f'<ul id="ctl00_cmptHijosSeg_lienzo_hijos" class="lienzo_hijos hijos_max3">{tracked}</ul>'
        f'<ul id="ctl00_cmptHijo_lista_users" class="lista_users">{picker}</ul>'
        "</body></html>"
    )


def _interstitial_reply(kind: Interstitial) -> dict[str, object]:
    match kind:
        case "CambiarPws":
            return {"CambiarPws": True, "Ruta": "/ACWeb/paginas/Publicas/CambiarPws.aspx"}
        case "TxtLegales":
            return {"TxtLegales": True, "Ruta": "/ACWeb/paginas/Publicas/TxtLegales.aspx"}
        case "OKCuenta":
            return {
                "OKCuenta": False,
                "GuidCuenta": synthetic_guid(0x501),
                "Ruta": "/ACWeb/paginas/Publicas/DatosCuenta.aspx",
            }
        case "MatOnline":
            return {"MatOnline": True, "Ruta": "/ACWeb/paginas/Publicas/MatOnline.aspx"}
        case "Classroom":
            return {
                "OK": True,
                "muetraOpClassroom": "https://classroom.invalid",
                "RutaHome": HOME_PATH,
            }


def _fault() -> JSONResponse:
    body = {"Message": "Error al procesar la solicitud.", "StackTrace": "", "ExceptionType": ""}
    return JSONResponse(body, status_code=500)


def _server_error() -> HTMLResponse:
    return HTMLResponse("<html><body>Error</body></html>", 500)


def _expired() -> JSONResponse:
    body = {"Message": "Error al procesar la solicitud.", "StackTrace": "", "ExceptionType": ""}
    return JSONResponse(body, status_code=401)


def _envelope(value: object) -> JSONResponse:
    return JSONResponse({"d": value})


def _widget(count: int) -> str:
    return f'<div class="seguimiento"><span class="numero"><em>{count}</em></span></div>'


class _Tracker:
    """Records every portal request and how many were in flight at once."""

    def __init__(self, app: ASGIApp, sim: "PortalSim") -> None:
        self._app = app
        self._sim = sim

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        status = 0

        async def tracked_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        sim = self._sim
        sim.in_flight += 1
        sim.max_in_flight = max(sim.max_in_flight, sim.in_flight)
        started = sim.clock.monotonic()
        try:
            await self._app(scope, receive, tracked_send)
        finally:
            sim.in_flight -= 1
            sim.requests.append(
                SimRequest(
                    method=str(scope["method"]),
                    path=str(scope["path"]),
                    status=status,
                    at=started,
                    query=bytes(scope["query_string"]).decode("latin-1"),
                )
            )


class _SimTransport(httpx.AsyncBaseTransport):
    """Runs the simulator in process, and turns a dropped response into a network error."""

    def __init__(self, app: ASGIApp) -> None:
        self._inner = httpx.ASGITransport(app=app)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            return await self._inner.handle_async_request(request)
        except SimDroppedError as error:
            raise httpx.ReadError("the simulator dropped the response", request=request) from error


@dataclass(slots=True)
class _Counters:
    check_session_calls: int = 0
    login_attempts: int = 0
    downloads: int = 0
    token_failures_left: int = 0
    failed_logins: dict[str, int] = field(default_factory=dict)


class PortalSim:
    def __init__(
        self,
        world: SimWorld | None = None,
        *,
        options: SimOptions | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.world = world or default_world()
        self.options = options or SimOptions()
        self.clock = clock or SystemClock()
        self.base_url = BASE_URL
        self.sessions: dict[str, SimSession] = {}
        self.requests: list[SimRequest] = []
        self.counters = _Counters()
        self.in_flight = 0
        self.max_in_flight = 0
        self.lesson_edits: dict[agenda.LessonKey, agenda.LessonEdit] = {}
        self.cancelled_lessons: set[agenda.LessonKey] = set()
        self.services: dict[str, Service] = {
            "WSHome.GetWPSeguimiento": Service(frozenset({"idAlumno"}), self._tracking),
            "WSReuniones.GetEmpleadosByHijo": Service(frozenset({"guidHijo"}), self._roster),
            "WSComunicados.GetArbolCarpetasJSON": Service(
                frozenset({"IsAutorizacion"}), self._folder_tree
            ),
            "WSComunicados.CarpetaSeleccionada": Service(
                frozenset({"idCarpeta", "IsAutorizacion", "TextoBusqueda"}), self._select_folder
            ),
            "WSComunicados.GetDatosPaginaComunicado": Service(
                frozenset(),
                self._message_data,
                referer=lambda session: _message_url(session.message_guid),
            ),
        }
        routes = [
            Route(LOGON_PATH, self._logon, methods=["GET"]),
            Route("/ACWeb/WS_Data/{service}.asmx/{method}", self._ws, methods=["POST"]),
            Route(HOME_PATH, self._home, methods=["GET"]),
            Route(MESSAGES_PATH, self._messages, methods=["GET"]),
            Route(MESSAGE_PATH, self._message, methods=["GET"]),
            Route(REPOSITORY_PATH, self._download, methods=["GET"]),
            Route(agenda.PAGE_PATH, self._agenda_page, methods=["GET"]),
            Route(agenda.FEED_PATH, self._agenda_feed, methods=["GET"]),
            Route("/ACWeb/paginas/General/MantenerSesion.aspx", self._keep_alive, methods=["GET"]),
            Route("/ACWeb/paginas/General/LogOff.aspx", self._log_off, methods=["GET"]),
        ]
        self.app = Starlette(routes=routes, middleware=[Middleware(_Tracker, sim=self)])

    def transport(self) -> httpx.AsyncBaseTransport:
        return _SimTransport(self.app)

    def expire_all_sessions(self) -> None:
        self.sessions.clear()

    @property
    def term(self) -> agenda.Term:
        """The school year that the simulator's clock is in, which the agenda is laid out for."""
        return agenda.term_of(self.clock.now().date())

    def edit_lesson(self, person_id: str, slot_id: str, day: date, edit: agenda.LessonEdit) -> None:
        """Change one lesson of one pupil on one day, as the school does in its timetable."""
        self.lesson_edits[(person_id, slot_id, day)] = edit

    def cancel_lesson(self, person_id: str, slot_id: str, day: date) -> None:
        self.cancelled_lessons.add((person_id, slot_id, day))

    def _session_of(self, request: Request) -> SimSession | None:
        return self.sessions.get(request.cookies.get(SESSION_COOKIE, ""))

    def _is_live(self, session: SimSession | None) -> bool:
        return (
            session is not None
            and session.stage == "authenticated"
            and self.clock.monotonic() - session.last_activity <= self.options.session_ttl_seconds
        )

    def _live_session(self, request: Request) -> SimSession | None:
        session = self._session_of(request)
        if session is None or not self._is_live(session):
            return None
        session.last_activity = self.clock.monotonic()
        return session

    async def _logon(self, request: Request) -> Response:
        if self.options.maintenance == "http503":
            return HTMLResponse("<html><body>Servicio no disponible</body></html>", 503)
        if self.options.maintenance == "page":
            return HTMLResponse("<html><body><h1>Sitio en mantenimiento</h1></body></html>")
        session = self._session_of(request)
        if session is None:
            session = SimSession(id=uuid.uuid4().hex, last_activity=self.clock.monotonic())
            self.sessions[session.id] = session
        session.token = uuid.uuid4().hex
        session.stage = "anonymous"
        session.family = None
        response = HTMLResponse(
            "<!DOCTYPE html><html><body><form>"
            f'<input name="Token" type="hidden" id="Token" value="{session.token}" />'
            '<input name="txtUsuario" type="text" id="txtUsuario" />'
            "</form></body></html>"
        )
        response.set_cookie(SESSION_COOKIE, session.id, path="/", httponly=True, samesite="lax")
        response.set_cookie(
            "LogOnToken",
            uuid.uuid4().hex,
            path="/",
            httponly=True,
            samesite="lax",
            max_age=14 * 86_400,
        )
        return response

    async def _ws(self, request: Request) -> Response:
        key = f"{request.path_params['service']}.{request.path_params['method']}"
        service = self.services.get(key)
        required = _AUTH_PARAMS.get(key)
        if required is None and service is not None:
            required = service.params
        if required is None:
            return HTMLResponse(_ERROR_REDIRECT_PAGE)
        try:
            params = json.loads(await request.body())
        except ValueError:
            return _fault()
        wants_json = "application/json" in request.headers.get("content-type", "")
        if not isinstance(params, dict) or set(params) != required or not wants_json:
            return _fault()

        session = self._session_of(request)
        valid_token = session is not None and session.token == params.get("token")
        known = session is not None and valid_token and session.stage != "anonymous"

        if key == "WSLogOn.Validar":
            return self._validar(request, session, valid_token, params)
        if key == "WSLogOn.GetRoles":
            return self._get_roles(known)
        if key == "WSLogOn.ValidarRol":
            return self._validar_rol(session if known else None, params)
        if key == "WSSesion.CheckSession":
            return self._check_session(session, params)
        if key == "WSHome.IsAppAccess":
            if session is None or not self._is_live(session):
                return _expired()
            session.last_activity = self.clock.monotonic()
            return _envelope(False)

        if service is None or session is None or not self._is_live(session):
            return _expired()
        session.last_activity = self.clock.monotonic()
        if service.referer is not None and self.options.require_referer:
            came_from = request.headers.get("referer", "")
            if not came_from.endswith(service.referer(session)):
                return _fault()
        try:
            return _envelope(service.handle(session, params))
        except SimFaultError:
            return _fault()

    def _validar(
        self,
        request: Request,
        session: SimSession | None,
        valid_token: bool,
        params: dict[str, Any],
    ) -> Response:
        if self.options.require_referer and "referer" not in request.headers:
            return _envelope(FAULT_TEXT)
        if session is None or not valid_token:
            return _envelope(EXPIRED_LOGON_TEXT)
        counters = self.counters
        if counters.token_failures_left > 0:
            counters.token_failures_left -= 1
            return _envelope(EXPIRED_LOGON_TEXT)
        counters.login_attempts += 1
        username = str(params["nickname"])
        limit = self.options.lock_after_failures
        if limit is not None and counters.failed_logins.get(username, 0) >= limit:
            return _envelope(LOCKED_TEXT)
        family = self.world.family_for(username)
        if family is None or family.password != params["password"]:
            counters.failed_logins[username] = counters.failed_logins.get(username, 0) + 1
            return _envelope(BAD_CREDENTIALS_TEXT)
        session.stage = "validated"
        session.family = family
        return _envelope("")

    def _get_roles(self, known: bool) -> Response:
        if not known:
            return _envelope({"Error": EXPIRED_LOGON_TEXT, "OK": None})
        roles = [
            {"Identificador": synthetic_guid(0x401 + index)} for index in range(self.options.roles)
        ]
        return _envelope(
            {
                "Error": None,
                "OK": roles,
                "multifactor": True if self.options.multifactor else None,
                "Ruta": None,
            }
        )

    def _validar_rol(self, session: SimSession | None, params: dict[str, Any]) -> Response:
        if session is None:
            return _envelope({"Error": EXPIRED_LOGON_TEXT})
        role_ids = {synthetic_guid(0x401 + index) for index in range(self.options.roles)}
        if str(params["idRol"]) not in role_ids:
            return _envelope({"Error": "Rol no válido."})
        if self.options.interstitial is not None:
            return _envelope(_interstitial_reply(self.options.interstitial))
        session.stage = "authenticated"
        session.last_activity = self.clock.monotonic()
        route = self.options.home_route or HOME_PATH
        return _envelope({"OK": True, "OKCuenta": True, "RutaHome": route})

    def _check_session(self, session: SimSession | None, params: dict[str, Any]) -> Response:
        self.counters.check_session_calls += 1
        if session is None or not self._is_live(session):
            return _expired()
        idle = int(params["contador"])
        if idle >= IDLE_LIMIT_MINUTES:
            return _envelope({"IsOk": False})
        if idle >= IDLE_LIMIT_MINUTES - 3:
            seconds = (IDLE_LIMIT_MINUTES - idle) * 60
            return _envelope(
                {
                    "Mensaje": f"Atención: {seconds} segundos para finalizar sesión.",
                    "IsOk": True,
                }
            )
        return _envelope({"IsOk": True})

    def _family_of(self, session: SimSession) -> SimFamily | None:
        """The family's data as it stands now, so a change shows to a session that is open."""
        if session.family is None:
            return None
        return self.world.family_for(session.family.username)

    def _child_of(self, session: SimSession, student_id: object) -> SimChild:
        family = self._family_of(session)
        if family is not None:
            for child in family.children:
                if child.student_id == student_id:
                    return child
        raise SimFaultError

    def _tracking(self, session: SimSession, params: dict[str, Any]) -> object:
        tracking = self._child_of(session, params["idAlumno"]).tracking
        return {
            "tareas": _widget(tracking.tasks),
            "actividades": _widget(tracking.activities),
            "anotaciones": _widget(tracking.notes),
            "controles": _widget(tracking.tests),
            "incidencias": _widget(tracking.incidents),
        }

    def _roster(self, session: SimSession, params: dict[str, Any]) -> object:
        child = self._child_of(session, params["guidHijo"])
        placeholder = {"Valor": "", "Texto": "-- Seleccione --"}
        staff = [
            {"Valor": member.id, "Texto": f"{member.name} ({member.role})"}
            for member in child.staff
        ]
        return [placeholder, *staff]

    def _mail_of(self, session: SimSession, folder: SimFolder) -> list[SimMessage]:
        family = self._family_of(session)
        held = family.messages if family else ()
        in_folder = (message for message in held if message.folder == folder)
        return sorted(in_folder, key=newest_first, reverse=True)

    def _folder_tree(self, session: SimSession, _params: dict[str, Any]) -> object:
        counts: dict[SimFolder, int] = {
            "received": len(self._mail_of(session, "received")),
            "sent": len(self._mail_of(session, "sent")),
        }
        return folder_tree(counts, session.folder)

    def _select_folder(self, session: SimSession, params: dict[str, Any]) -> object:
        folder = FOLDER_OF_ID[str(params["idCarpeta"])]
        session.folder = folder
        return folder_selection(folder)

    async def _messages(self, request: Request) -> Response:
        session = self._live_session(request)
        if session is None or self._family_of(session) is None:
            return RedirectResponse(
                f"{LOGON_PATH}?ReturnUrl={quote(MESSAGES_PATH, safe='')}", status_code=302
            )
        query = dict(request.query_params)
        ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
        numeric = set(query) == FEED_QUERY and all(query[n].isdecimal() for n in _FEED_NUMBERS)
        if not (ajax and numeric) or int(query["rows"]) < 1 or int(query["page"]) < 1:
            return _server_error()
        rows, page = int(query["rows"]), int(query["page"])
        held = self._mail_of(session, session.folder)
        grid = {
            "page": page,
            "total": math.ceil(len(held) / rows),
            "records": len(held),
            "rows": [self._feed_row(message) for message in held[(page - 1) * rows : page * rows]],
            "userdata": {},
        }
        return HTMLResponse(html_safe_json(grid))

    def _feed_row(self, message: SimMessage) -> dict[str, object]:
        cells = feed_cells(message)
        width = self.options.feed_cell_count
        if width is not None:
            cells = [cells[index] if index < len(cells) else "" for index in range(width)]
        return {"id": message.guid, "cell": cells}

    def _message_of(self, session: SimSession, guid: str | None) -> SimMessage | None:
        family = self._family_of(session)
        held = family.messages if family else ()
        return next((message for message in held if message.guid == guid), None)

    async def _message(self, request: Request) -> Response:
        session = self._live_session(request)
        if session is None or self._family_of(session) is None:
            return RedirectResponse(
                f"{LOGON_PATH}?ReturnUrl={quote(MESSAGE_PATH, safe='')}", status_code=302
            )
        query = dict(request.query_params)
        shaped = (
            set(query) == _MESSAGE_QUERY
            and query["TipoComunicado"] == "N"
            and query["AccionComunicado"] == "1"
            and not (
                query["DestsInicialesCom"] or query["TxtDefaultCom"] or query["AccionExtraCom"]
            )
        )
        came_from = request.headers.get("referer", "")
        from_the_list = came_from.endswith(MESSAGES_PATH) or not self.options.require_referer
        message = self._message_of(session, query.get("GuidComunicadoOrigen"))
        if not (shaped and from_the_list) or message is None:
            return _server_error()
        session.message_guid = message.guid
        return HTMLResponse(
            "<!DOCTYPE html><html><head><title>Comunicado</title></head><body></body></html>"
        )

    def _message_data(self, session: SimSession, _params: dict[str, Any]) -> object:
        message = self._message_of(session, session.message_guid)
        if message is None:
            raise SimFaultError
        data = message_dto(message)
        if self.options.message_time is not None:
            data["HoraPublicacion"] = self.options.message_time
        return data

    async def _download(self, request: Request) -> Response:
        session = self._live_session(request)
        if session is None or self._family_of(session) is None:
            return RedirectResponse(
                f"{LOGON_PATH}?ReturnUrl={quote(REPOSITORY_PATH, safe='')}", status_code=302
            )
        self.counters.downloads += 1
        query = dict(request.query_params)
        message = self._message_of(session, session.message_guid)
        files = message.files if message is not None else ()
        file = next((item for item in files if item.id == query.get("nombre")), None)
        came_from = request.headers.get("referer", "")
        from_the_message = (
            came_from.endswith(_message_url(session.message_guid))
            or not self.options.require_referer
        )
        shaped = (
            set(query) == _DOWNLOAD_QUERY
            and query["tipo"] == "6"
            and file is not None
            and query["alias"] == file.name
            and request.headers.get("accept") == "*/*"
        )
        if not (shaped and from_the_message) or file is None:
            return _server_error()
        if self.options.download_as_page:
            return HTMLResponse(_DOWNLOAD_FAILED_PAGE)
        extra = self.options.download_extra_bytes
        data = file.data[:extra] if extra < 0 else file.data + b"\x00" * extra
        return Response(data, media_type="application/octet-stream")

    async def _agenda_page(self, request: Request) -> Response:
        session = self._live_session(request)
        family = self._family_of(session) if session is not None else None
        if session is None or family is None:
            return RedirectResponse(
                f"{LOGON_PATH}?ReturnUrl={quote(agenda.PAGE_PATH, safe='')}", status_code=302
            )
        opened = agenda.page_target(
            dict(request.query_params),
            {child.person_id for child in family.children},
            family.guardian.person_id,
        )
        if opened is None:
            return _server_error()
        session.open_agenda = opened
        return HTMLResponse('<html><body><div id="calendar"></div></body></html>')

    async def _agenda_feed(self, request: Request) -> Response:
        session = self._live_session(request)
        family = self._family_of(session) if session is not None else None
        if session is None or family is None:
            return RedirectResponse(
                f"{LOGON_PATH}?ReturnUrl={quote(agenda.FEED_PATH, safe='')}", status_code=302
            )
        if self.options.agenda_feed_fails:
            return _server_error()
        if self.options.agenda_not_json:
            return HTMLResponse('<html><body><input id="txtUsuario" /></body></html>')
        asked = agenda.feed_seconds(dict(request.query_params))
        opened = session.open_agenda
        ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
        came_from = request.headers.get("referer", "")
        from_the_page = opened is not None and (
            came_from.endswith(agenda.page_url(*opened)) or not self.options.require_referer
        )
        if asked is None or opened is None or not ajax or not from_the_page:
            return _server_error()
        entries = self._agenda_entries(family, opened, *asked)
        if self.options.agenda_bad_event and entries:
            entries[0] = {**entries[0], "start": "tomorrow morning"}
        return JSONResponse(entries)

    def _agenda_entries(
        self,
        family: SimFamily,
        opened: tuple[agenda.SimAgendaScope, str],
        start: int,
        end: int,
    ) -> list[dict[str, object]]:
        scope, person_id = opened
        term = self.term
        first, last = agenda.asked_days(start, end)
        if self.options.agenda_ignores_end:
            last = max(last, term.last)
        school_window = None if self.options.agenda_standing_events else (first, last)
        object_guid = synthetic_guid(0x7F00)
        child = next((item for item in family.children if item.person_id == person_id), None)
        school = agenda.occasions_in(
            (*self.world.calendar, *(child.events if child else ())),
            term,
            class_name=agenda.SCHOOL_EVENT_CLASS,
            object_type=agenda.SCHOOL_EVENT_OBJECT,
            object_guid=object_guid,
            window=school_window,
        )
        if scope == "guardian":
            interviews = agenda.occasions_in(
                family.guardian.interviews,
                term,
                class_name=agenda.INTERVIEW_CLASS,
                object_type=agenda.INTERVIEW_OBJECT,
                object_guid=object_guid,
                window=(first, last),
            )
            return [*school, *interviews]
        lessons = agenda.lessons_between(
            first,
            last,
            term,
            person_id,
            child.timetable if child else (),
            edits=self.lesson_edits,
            cancelled=self.cancelled_lessons,
            object_guid=object_guid,
        )
        return [*lessons, *school]

    async def _home(self, request: Request) -> Response:
        session = self._live_session(request)
        family = self._family_of(session) if session is not None else None
        if family is None:
            return RedirectResponse(
                f"{LOGON_PATH}?ReturnUrl={quote(HOME_PATH, safe='')}", status_code=302
            )
        return HTMLResponse(
            render_home(family, guardian_listed=not self.options.home_without_guardian)
        )

    async def _keep_alive(self, request: Request) -> Response:
        self._live_session(request)
        return HTMLResponse("")

    async def _log_off(self, request: Request) -> Response:
        session = self._session_of(request)
        if session is not None:
            self.sessions.pop(session.id, None)
        return RedirectResponse(LOGON_PATH, status_code=302)
