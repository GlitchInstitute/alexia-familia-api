"""Everything that can go wrong between this server and the portal.

Failures are a closed union with one class per way the portal can fail. `describe` and the HTTP
mapping in `alexia_api.api.errors` both `match` on it and end in `assert_never`, so a new class
fails type checking until every consumer handles it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Final, Literal, assert_never

from alexia_api.domain.media import MEBIBYTE

Interstitial = Literal["CambiarPws", "TxtLegales", "OKCuenta", "MatOnline", "Classroom"]
TransportReason = Literal["timeout", "network", "redirect", "blocked", "too_large"]
DenialReason = Literal[
    "not_on_allowlist",
    "never_call",
    "writes_disabled",
    "forms_disabled",
    "unread_restore_disabled",
]
BreakerCause = Literal[
    "invalid_credentials",
    "refused_login",
    "mfa_required",
    "action_required_in_portal",
    "state_unreadable",
]

BREAKER_CAUSE_TEXT: Final[Mapping[BreakerCause, str]] = {
    "invalid_credentials": "the portal rejected the user name or password",
    "refused_login": "the portal refused the login",
    "mfa_required": "the portal asked for a multifactor PIN",
    "action_required_in_portal": "the portal asked for a step in a browser",
    "state_unreadable": "the saved block file could not be read",
}

MAX_DRIFT_SAMPLE_CHARS: Final = 64 * 1024


@dataclass(frozen=True, slots=True)
class NoCredentials:
    """The account has no portal user name or password configured."""

    code: ClassVar[str] = "no_credentials"


@dataclass(frozen=True, slots=True)
class InvalidCredentials:
    """The portal said the user name or password is wrong. Trying again can lock the account."""

    portal_text: str
    code: ClassVar[str] = "invalid_credentials"


@dataclass(frozen=True, slots=True)
class RefusedLogin:
    """The portal refused the login with a message this server does not recognise."""

    portal_text: str
    code: ClassVar[str] = "refused_login"


@dataclass(frozen=True, slots=True)
class MfaRequired:
    """The account asks for a multifactor PIN, which cannot be automated."""

    code: ClassVar[str] = "mfa_required"


@dataclass(frozen=True, slots=True)
class ActionRequiredInPortal:
    """The portal shows a page the guardian has to complete in a browser first."""

    interstitial: Interstitial
    code: ClassVar[str] = "action_required_in_portal"


@dataclass(frozen=True, slots=True)
class RoleChoiceRequired:
    """The login has several roles and the configuration names none of them."""

    role_count: int
    code: ClassVar[str] = "role_choice_required"


@dataclass(frozen=True, slots=True)
class NoRole:
    """The login has no role at all."""

    code: ClassVar[str] = "no_role"


@dataclass(frozen=True, slots=True)
class PortalMaintenance:
    """The portal answered with a status that means maintenance or an outage."""

    status: int
    code: ClassVar[str] = "portal_maintenance"


@dataclass(frozen=True, slots=True)
class TokenInvalid:
    """The portal said the login token it handed out is no longer valid."""

    code: ClassVar[str] = "token_invalid"


@dataclass(frozen=True, slots=True)
class PortalFault:
    """The portal reported an unhandled server fault in its own words."""

    portal_text: str
    code: ClassVar[str] = "portal_fault"


@dataclass(frozen=True, slots=True)
class WsRejected:
    """A script service call came back with an error status."""

    call: str
    status: int
    code: ClassVar[str] = "ws_rejected"


@dataclass(frozen=True, slots=True)
class SessionExpired:
    """The portal no longer accepts the session cookie."""

    code: ClassVar[str] = "session_expired"


@dataclass(frozen=True, slots=True)
class UnexpectedReply:
    """The portal sent something that is not in any shape this server knows."""

    where: str
    code: ClassVar[str] = "unexpected_reply"


@dataclass(frozen=True, slots=True)
class SchemaDrift:
    """A known call came back in a changed shape. The reply is kept for diagnosis."""

    where: str
    sample: str
    code: ClassVar[str] = "portal_changed"


@dataclass(frozen=True, slots=True)
class Transport:
    """The network call failed before the portal gave an answer."""

    reason: TransportReason
    status: int | None = None
    code: ClassVar[str] = "transport"


@dataclass(frozen=True, slots=True)
class AttachmentTooLarge:
    """A file is bigger than the operator allows this server to carry, so it was not fetched.

    The limit is in bytes. The setting that holds it counts whole mebibytes.
    """

    limit: int
    code: ClassVar[str] = "attachment_too_large"


@dataclass(frozen=True, slots=True)
class Denied:
    """The server's own rules refused a call before it left the process."""

    call: str
    reason: DenialReason
    code: ClassVar[str] = "denied"


@dataclass(frozen=True, slots=True)
class ComposeRejected:
    """The portal refused to save or send a message."""

    call: str
    portal_text: str
    portal_code: str | None
    code: ClassVar[str] = "compose_rejected"


@dataclass(frozen=True, slots=True)
class ComposeMismatch:
    """The portal's saved copy of a message differs from what was prepared."""

    where: str
    code: ClassVar[str] = "compose_mismatch"


@dataclass(frozen=True, slots=True)
class BreakerOpen:
    """Automatic logins are paused because an earlier login failure could lock the account."""

    since: datetime
    cause: BreakerCause
    code: ClassVar[str] = "breaker_open"


type PortalErrorDetail = (
    NoCredentials
    | InvalidCredentials
    | RefusedLogin
    | MfaRequired
    | ActionRequiredInPortal
    | RoleChoiceRequired
    | NoRole
    | PortalMaintenance
    | TokenInvalid
    | PortalFault
    | WsRejected
    | SessionExpired
    | UnexpectedReply
    | SchemaDrift
    | Transport
    | AttachmentTooLarge
    | Denied
    | ComposeRejected
    | ComposeMismatch
    | BreakerOpen
)


def breaker_cause(detail: PortalErrorDetail) -> BreakerCause | None:
    """Name the failure when it can lock the account, so logins pause until an operator resets."""
    match detail:
        case InvalidCredentials():
            return "invalid_credentials"
        case RefusedLogin():
            return "refused_login"
        case MfaRequired():
            return "mfa_required"
        case ActionRequiredInPortal():
            return "action_required_in_portal"
        case _:
            return None


def sample_of(text: str) -> str:
    return text[:MAX_DRIFT_SAMPLE_CHARS]


def describe(detail: PortalErrorDetail) -> str:
    match detail:
        case NoCredentials():
            return "the portal credentials are not configured for this account"
        case InvalidCredentials(portal_text=text):
            return f'the portal rejected the user name or password and said "{text}"'
        case RefusedLogin(portal_text=text):
            return f'the portal refused the login with an unrecognised message and said "{text}"'
        case MfaRequired():
            return "the account asks for a multifactor PIN, which this server cannot enter"
        case ActionRequiredInPortal(interstitial=page):
            return f"the portal wants you to finish a step in a browser first ({page})"
        case RoleChoiceRequired(role_count=count):
            return f"the account has {count} roles and the configuration names none of them"
        case NoRole():
            return "the account has no role"
        case PortalMaintenance(status=status):
            return f"the portal looks to be in maintenance (HTTP {status})"
        case TokenInvalid():
            return "the portal said the login token is no longer valid"
        case PortalFault(portal_text=text):
            return f'the portal reported a server fault and said "{text}"'
        case WsRejected(call=call, status=status):
            return f"the portal rejected {call} (HTTP {status})"
        case SessionExpired():
            return "the portal session has expired"
        case UnexpectedReply(where=where):
            return f"the portal sent a reply this server does not understand ({where})"
        case SchemaDrift(where=where):
            return f"the portal changed the shape of {where}"
        case Transport(reason=reason):
            return f"the network call to the portal failed ({reason})"
        case AttachmentTooLarge(limit=limit):
            return (
                f"the file is larger than the {limit // MEBIBYTE} MiB this server carries, "
                "set ALEXIA_API_MAX_ATTACHMENT_MIB to a higher number to allow it, "
                "or open the message in the portal to get the file"
            )
        case Denied(call=call, reason="writes_disabled"):
            return (
                f"{call} writes to the portal and writes are switched off, "
                "set ALEXIA_API_ALLOW_WRITES to true to allow them"
            )
        case Denied(call=call, reason="forms_disabled"):
            return f"{call} is switched off, set ALEXIA_API_ALLOW_FORMS to true to allow it"
        case Denied(call=call, reason="unread_restore_disabled"):
            return (
                f"{call} puts a message back to unread and that is switched off, "
                "set ALEXIA_API_RESTORE_UNREAD to true to allow it"
            )
        case Denied(call=call, reason=reason):
            return f"{call} is not allowed ({reason})"
        case ComposeRejected(call=call, portal_text=text):
            return f'the portal refused {call} and said "{text}"'
        case ComposeMismatch(where=where):
            return (
                f"the portal's copy of the message does not match what was prepared ({where}), "
                "nothing was sent"
            )
        case BreakerOpen(cause=cause):
            return (
                f"automatic logins are paused because {BREAKER_CAUSE_TEXT[cause]}, "
                "fix the cause and reset the block with alexia-api accounts reset"
            )
        case _:
            assert_never(detail)


class PortalError(Exception):
    """Raised for every portal failure. The typed reason is in `detail`."""

    def __init__(self, detail: PortalErrorDetail) -> None:
        super().__init__(describe(detail))
        self.detail = detail
