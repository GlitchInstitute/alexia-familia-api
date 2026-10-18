"""Errors as RFC 9457 problem documents.

Every failure that reaches a client has the same shape and a stable `code`. A client branches on
`code`, shows `detail` to a person, and quotes `request_id` in a bug report. The portal's own
words reach `detail` only where `describe` puts them, and the sample of a reply that changed
shape never leaves the server.

The status says who has to act. A 4xx status means the caller can fix the request. A 503 means
this account cannot be used until the operator acts, for example after a wrong password. A 502 or
504 means the portal misbehaved or did not answer.
"""

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Final, assert_never, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import AwareDatetime, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from alexia_api.api.middleware import protective_headers
from alexia_api.domain.base import Model
from alexia_api.domain.errors import (
    ActionRequiredInPortal,
    BreakerCause,
    BreakerOpen,
    ComposeMismatch,
    ComposeRejected,
    DenialReason,
    Denied,
    Interstitial,
    InvalidCredentials,
    MfaRequired,
    NoCredentials,
    NoRole,
    PortalError,
    PortalErrorDetail,
    PortalFault,
    PortalMaintenance,
    RefusedLogin,
    RoleChoiceRequired,
    SchemaDrift,
    SessionExpired,
    TokenInvalid,
    Transport,
    UnexpectedReply,
    WsRejected,
    describe,
)
from alexia_api.domain.security import Scope
from alexia_api.services.errors import NotFoundError

if TYPE_CHECKING:
    from starlette.types import ExceptionHandler

log = logging.getLogger("alexia_api.error")

PROBLEM_MEDIA_TYPE: Final = "application/problem+json"
UNKNOWN_REQUEST: Final = "unknown"
MAX_ECHOED_CHARACTERS: Final = 80
PAYLOAD_TOO_LARGE: Final = 413
UNPROCESSABLE: Final = 422

_TITLES: Final[Mapping[int, str]] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    PAYLOAD_TOO_LARGE: "Content Too Large",
    UNPROCESSABLE: "Unprocessable Content",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


def title_of(status: int) -> str:
    """The standard name of a status.

    Python renamed a few between 3.12 and 3.13, and a response must read the same on both, so the
    statuses this API uses are fixed here.
    """
    if status in _TITLES:
        return _TITLES[status]
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


class FieldProblem(Model):
    """One thing wrong with the request, and where it was."""

    location: tuple[str | int, ...] = Field(
        description='Where the problem is, for example ["query", "fresh"].'
    )
    message: str


class Problem(Model):
    """An RFC 9457 problem document. Members past `request_id` appear only when they apply."""

    type: str = Field(
        default="about:blank",
        description="Always about:blank. Use `code`, which is stable, to tell problems apart.",
    )
    title: str = Field(description="The standard name of the HTTP status.")
    status: int = Field(description="The HTTP status of the response.")
    detail: str = Field(description="What went wrong and what to do about it, for a person.")
    code: str = Field(description="A stable name for the problem. Branch on this, not on text.")
    request_id: str = Field(description="Quote this when you report a bug.")
    cause: BreakerCause | None = Field(
        default=None, description="Why logins are paused, when the account is blocked."
    )
    since: AwareDatetime | None = Field(
        default=None, description="When logins were paused, when the account is blocked."
    )
    interstitial: Interstitial | None = Field(
        default=None, description="The portal page that wants a person, in a browser."
    )
    reason: DenialReason | None = Field(
        default=None, description="Which of the operator's switches refused the call."
    )
    needed: Scope | None = Field(
        default=None, description="The scope the key would need, when it lacks one."
    )
    retry_after_seconds: int | None = Field(
        default=None, description="How long to wait before asking again, when rate limited."
    )
    errors: tuple[FieldProblem, ...] | None = Field(
        default=None, description="The parts of the request that are not valid."
    )


class ApiError(Exception):
    """A refusal that the API decides on by itself, such as a missing key."""

    def __init__(
        self,
        status: int,
        code: str,
        detail: str,
        *,
        headers: Mapping[str, str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.headers = dict(headers or {})
        self.extra = extra


@dataclass(frozen=True, slots=True)
class Mapped:
    """How a portal failure appears over HTTP."""

    status: int
    extra: Mapping[str, object] = field(default_factory=dict)


def map_portal_error(detail: PortalErrorDetail) -> Mapped:
    """Choose the status and the extra members for a portal failure.

    The `match` has no default branch, so a new failure class fails type checking until it is
    given a status here.
    """
    match detail:
        case (
            NoCredentials()
            | InvalidCredentials()
            | RefusedLogin()
            | MfaRequired()
            | RoleChoiceRequired()
            | NoRole()
            | PortalMaintenance()
        ):
            return Mapped(HTTPStatus.SERVICE_UNAVAILABLE)
        case ActionRequiredInPortal(interstitial=page):
            return Mapped(HTTPStatus.SERVICE_UNAVAILABLE, {"interstitial": page})
        case BreakerOpen(since=since, cause=cause):
            return Mapped(HTTPStatus.SERVICE_UNAVAILABLE, {"since": since, "cause": cause})
        case Transport(reason="timeout"):
            return Mapped(HTTPStatus.GATEWAY_TIMEOUT)
        case Transport():
            return Mapped(HTTPStatus.BAD_GATEWAY)
        case (
            TokenInvalid()
            | PortalFault()
            | WsRejected()
            | SessionExpired()
            | UnexpectedReply()
            | SchemaDrift()
            | ComposeMismatch()
        ):
            return Mapped(HTTPStatus.BAD_GATEWAY)
        case ComposeRejected():
            return Mapped(UNPROCESSABLE)
        case Denied(reason="not_on_allowlist" | "never_call"):
            return Mapped(HTTPStatus.INTERNAL_SERVER_ERROR)
        case Denied(reason=reason):
            return Mapped(HTTPStatus.FORBIDDEN, {"reason": reason})
        case _:
            assert_never(detail)


def request_id_of(request: Request) -> str:
    return str(getattr(request.state, "request_id", UNKNOWN_REQUEST))


def problem_response(
    request: Request,
    status: int,
    code: str,
    detail: str,
    *,
    headers: Mapping[str, str] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> JSONResponse:
    request_id = request_id_of(request)
    problem = Problem(
        title=title_of(status),
        status=status,
        detail=detail,
        code=code,
        request_id=request_id,
        **(extra or {}),
    )
    return JSONResponse(
        problem.model_dump(mode="json", exclude_none=True),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers={**protective_headers(), **(headers or {}), "X-Request-Id": request_id},
    )


def _shown(reference: str) -> str:
    if len(reference) <= MAX_ECHOED_CHARACTERS:
        return reference
    return reference[:MAX_ECHOED_CHARACTERS] + "..."


async def _api_error(request: Request, error: ApiError) -> Response:
    return problem_response(
        request, error.status, error.code, error.detail, headers=error.headers, extra=error.extra
    )


async def _not_found(request: Request, error: NotFoundError) -> Response:
    reference = _shown(error.reference)
    if error.kind == "account":
        detail = f"no account named '{reference}' is available to this key"
    else:
        detail = (
            f"no child '{reference}' on this account, use a student id or a name from the list of "
            "children, and ask for that list with fresh=true if a sibling was added lately"
        )
    return problem_response(request, HTTPStatus.NOT_FOUND, f"{error.kind}_not_found", detail)


async def _portal_error(request: Request, error: PortalError) -> Response:
    mapped = map_portal_error(error.detail)
    return problem_response(
        request, mapped.status, error.detail.code, describe(error.detail), extra=mapped.extra
    )


async def _validation_error(request: Request, error: RequestValidationError) -> Response:
    problems = [
        FieldProblem(location=tuple(item["loc"]), message=str(item["msg"]))
        for item in error.errors()
    ]
    return problem_response(
        request,
        UNPROCESSABLE,
        "validation_error",
        "the request is not valid, see errors for what to change",
        extra={"errors": problems},
    )


_HTTP_CODES: Final[Mapping[int, tuple[str, str]]] = {
    HTTPStatus.NOT_FOUND: ("not_found", "no endpoint answers at this address"),
    HTTPStatus.METHOD_NOT_ALLOWED: (
        "method_not_allowed",
        "this method is not allowed here, the Allow header lists the ones that are",
    ),
    PAYLOAD_TOO_LARGE: (
        "payload_too_large",
        "the request body is larger than this server accepts",
    ),
}


async def _http_error(request: Request, error: StarletteHTTPException) -> Response:
    code, detail = _HTTP_CODES.get(
        error.status_code, (f"http_{error.status_code}", title_of(error.status_code))
    )
    return problem_response(
        request, error.status_code, code, detail, headers=dict(error.headers or {})
    )


async def _unhandled(request: Request, error: Exception) -> Response:
    request_id = request_id_of(request)
    log.error("unhandled %s", type(error).__name__, extra={"request_id": request_id})
    return problem_response(
        request,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        "internal_error",
        "something went wrong inside the server, quote the request id to the operator",
    )


def _handle[E: Exception](
    app: FastAPI, kind: type[E], handler: Callable[[Request, E], Awaitable[Response]]
) -> None:
    app.add_exception_handler(kind, cast("ExceptionHandler", handler))


def install_handlers(app: FastAPI) -> None:
    """Make every failure a problem document."""
    _handle(app, ApiError, _api_error)
    _handle(app, NotFoundError, _not_found)
    _handle(app, PortalError, _portal_error)
    _handle(app, RequestValidationError, _validation_error)
    _handle(app, StarletteHTTPException, _http_error)
    _handle(app, Exception, _unhandled)


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """The `responses` entries that document problems in OpenAPI."""
    return {status: {"model": Problem, "description": title_of(status)} for status in statuses}
