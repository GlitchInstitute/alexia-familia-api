"""Signing in.

The portal's flow is a token from the logon page, then three script calls. The first checks the
password, the second lists the roles, and the third picks one and returns the home address. A
failure can lock the account, so this module names each refusal exactly and never retries a
password. The only retry is for a stale token, which does not send the password a second time
until the portal has said the token itself was the problem.
"""

import re
from dataclasses import dataclass
from typing import Final

from pydantic import SecretStr
from selectolax.lexbor import LexborHTMLParser

from alexia_api.domain.errors import (
    ActionRequiredInPortal,
    Interstitial,
    InvalidCredentials,
    MfaRequired,
    NoRole,
    PortalError,
    PortalErrorDetail,
    PortalFault,
    PortalMaintenance,
    RefusedLogin,
    RoleChoiceRequired,
    TokenInvalid,
    UnexpectedReply,
)
from alexia_api.domain.ids import RoleId, parse_role_id
from alexia_api.portal import wire
from alexia_api.portal.allowlist import GET_ROLES, VALIDAR, VALIDAR_ROL
from alexia_api.portal.children import HomeSnapshot, parse_home
from alexia_api.portal.session import PortalRequest, PortalSession, Tx
from alexia_api.portal.ws import (
    LOGON_PATH,
    MAINTENANCE_STATUSES,
    call_ws,
    logon_path,
)

_PORTAL_FAULT: Final = re.compile(
    r"referencia a objeto|object reference|excepci[oó]n|exception", re.IGNORECASE
)
_TOKEN_INVALID: Final = re.compile(r"token|sesi[oó]n ha caducado", re.IGNORECASE)
_BAD_CREDENTIALS: Final = re.compile(
    r"(usuario|contrase[ñn]a|password|credencial|clave|c[oó]digo de acceso)"
    r".*(incorrect|inv[aá]lid|err[oó]ne)"
    r"|(incorrect|inv[aá]lid|err[oó]ne).*(usuario|contrase[ñn]a|password|credencial)",
    re.IGNORECASE,
)
_MAINTENANCE: Final = re.compile(r"mantenimiento|maintenance", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PortalCredentials:
    user: SecretStr
    password: SecretStr
    institution_key: str


@dataclass(frozen=True, slots=True)
class LoginOk:
    role_id: RoleId
    role_count: int
    home: HomeSnapshot


def classify_refusal(text: str) -> PortalErrorDetail:
    """Name a refusal by what the portal said. The order matters, a fault beats a bad password."""
    if _PORTAL_FAULT.search(text):
        return PortalFault(portal_text=text)
    if _TOKEN_INVALID.search(text):
        return TokenInvalid()
    if _BAD_CREDENTIALS.search(text):
        return InvalidCredentials(portal_text=text)
    return RefusedLogin(portal_text=text)


def _interstitial_of(reply: wire.ValidarRolReply) -> Interstitial | None:
    if reply.change_password is not None:
        return "CambiarPws"
    if reply.legal_text is not None:
        return "TxtLegales"
    if reply.account_confirmed is False:
        return "OKCuenta"
    if reply.online_enrollment is not None:
        return "MatOnline"
    if reply.show_classroom:
        return "Classroom"
    return None


async def _fetch_token(tx: Tx, institution_key: str) -> str:
    response = await tx.request(PortalRequest(method="GET", path=logon_path(institution_key)))
    if response.status in MAINTENANCE_STATUSES:
        raise PortalError(PortalMaintenance(status=response.status))
    if response.status != 200:
        raise PortalError(UnexpectedReply(where=f"logon page HTTP {response.status}"))
    html = response.text()
    field = LexborHTMLParser(html).css_first("#Token")
    token = field.attributes.get("value") if field is not None else None
    if not token:
        if _MAINTENANCE.search(html):
            raise PortalError(PortalMaintenance(status=response.status))
        raise PortalError(UnexpectedReply(where="logon page has no Token field"))
    return token


async def check_login_page(tx: Tx, institution_key: str) -> None:
    """Open the portal's login page and check that it has the field a login needs.

    No credentials are sent, so this cannot count as a failed login and cannot lock the account.
    """
    await _fetch_token(tx, institution_key)


def _home_path(tx: Tx, home_route: str) -> str:
    resolved = tx.absolute(home_route)
    root = tx.absolute("/")
    if not resolved.startswith(root):
        raise PortalError(UnexpectedReply(where="RutaHome points off the portal"))
    return resolved.removeprefix(root.rstrip("/"))


async def _choose_role(tx: Tx, token: str, role_id: RoleId | None) -> tuple[RoleId, int]:
    referer = tx.absolute(LOGON_PATH)
    reply = await call_ws(tx, GET_ROLES, wire.GetRolesParams(token=token), referer=referer)
    if reply.error:
        raise PortalError(classify_refusal(reply.error))
    available = reply.roles or []
    if not available:
        raise PortalError(NoRole())
    if reply.multifactor:
        raise PortalError(MfaRequired())
    identifiers = [parse_role_id(role.identifier) for role in available]
    if role_id is not None:
        if role_id not in identifiers:
            raise PortalError(RoleChoiceRequired(role_count=len(available)))
        return role_id, len(available)
    if len(identifiers) == 1:
        return identifiers[0], 1
    raise PortalError(RoleChoiceRequired(role_count=len(available)))


async def _complete(tx: Tx, token: str, role_id: RoleId | None) -> LoginOk:
    referer = tx.absolute(LOGON_PATH)
    chosen, role_count = await _choose_role(tx, token, role_id)

    validated = await call_ws(
        tx,
        VALIDAR_ROL,
        wire.ValidarRolParams(token=token, role_id=chosen, evaluate_multifactor=False),
        referer=referer,
    )
    interstitial = _interstitial_of(validated)
    if interstitial is not None:
        raise PortalError(ActionRequiredInPortal(interstitial=interstitial))
    if validated.error:
        raise PortalError(classify_refusal(validated.error))
    if validated.ok is not True or not validated.home_route:
        raise PortalError(UnexpectedReply(where="ValidarRol without RutaHome"))

    home = await tx.request(
        PortalRequest(method="GET", path=_home_path(tx, validated.home_route), referer=referer)
    )
    if home.status != 200:
        raise PortalError(UnexpectedReply(where=f"home page HTTP {home.status}"))
    return LoginOk(role_id=chosen, role_count=role_count, home=parse_home(home.text()))


async def _attempt(
    session: PortalSession, credentials: PortalCredentials, role_id: RoleId | None
) -> LoginOk | PortalErrorDetail:
    token = await _fetch_token(session, credentials.institution_key)
    reply = await call_ws(
        session,
        VALIDAR,
        wire.ValidarParams(
            token=token,
            nickname=credentials.user.get_secret_value(),
            password=credentials.password.get_secret_value(),
        ),
        referer=session.absolute(LOGON_PATH),
    )
    if reply == "":
        return await _complete(session, token, role_id)
    return classify_refusal(reply)


async def login(
    session: PortalSession,
    credentials: PortalCredentials,
    *,
    role_id: RoleId | None = None,
) -> LoginOk:
    """Sign in and return the chosen role and the home page.

    The password is sent once. If the portal answers that the token is stale, the first reply
    proves the password was not judged, so one fresh token and one more attempt are allowed.
    """
    try:
        session.clear_cookies()
        outcome = await _attempt(session, credentials, role_id)
        if isinstance(outcome, TokenInvalid):
            session.clear_cookies()
            outcome = await _attempt(session, credentials, role_id)
    except BaseException:
        session.clear_cookies()
        raise
    if isinstance(outcome, LoginOk):
        return outcome
    session.clear_cookies()
    raise PortalError(outcome)
