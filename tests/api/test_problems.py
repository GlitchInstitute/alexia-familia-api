import logging
from datetime import UTC, datetime
from typing import NoReturn, get_args

import pytest

from alexia_api.api.errors import map_portal_error, title_of
from alexia_api.domain.errors import (
    ActionRequiredInPortal,
    BreakerOpen,
    ComposeMismatch,
    ComposeRejected,
    Denied,
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
)
from alexia_api.services.registry import AccountRuntime
from tests.api.support import Api, problem_of

SINCE = datetime(2026, 1, 12, 8, 0, tzinfo=UTC)

EXPECTED_STATUS: tuple[tuple[PortalErrorDetail, int], ...] = (
    (NoCredentials(), 503),
    (InvalidCredentials("wrong"), 503),
    (RefusedLogin("locked"), 503),
    (MfaRequired(), 503),
    (ActionRequiredInPortal("CambiarPws"), 503),
    (RoleChoiceRequired(2), 503),
    (NoRole(), 503),
    (PortalMaintenance(503), 503),
    (BreakerOpen(SINCE, "invalid_credentials"), 503),
    (Transport("timeout"), 504),
    (Transport("network"), 502),
    (Transport("redirect"), 502),
    (Transport("blocked"), 502),
    (Transport("too_large"), 502),
    (TokenInvalid(), 502),
    (PortalFault("boom"), 502),
    (WsRejected("WSHome.Call", 500), 502),
    (SessionExpired(), 502),
    (UnexpectedReply("home"), 502),
    (SchemaDrift("home", "<html>"), 502),
    (ComposeMismatch("subject"), 502),
    (ComposeRejected("send", "refused", None), 422),
    (Denied("send", "writes_disabled"), 403),
    (Denied("answer", "forms_disabled"), 403),
    (Denied("restore", "unread_restore_disabled"), 403),
    (Denied("call", "not_on_allowlist"), 500),
    (Denied("call", "never_call"), 500),
)


def test_the_table_has_every_class_of_failure() -> None:
    classes = set(get_args(PortalErrorDetail.__value__))
    assert {type(detail) for detail, _ in EXPECTED_STATUS} == classes


@pytest.mark.parametrize(("detail", "status"), EXPECTED_STATUS, ids=repr)
def test_each_failure_has_the_status_that_says_who_must_act(
    detail: PortalErrorDetail, status: int
) -> None:
    assert map_portal_error(detail).status == status


def test_the_extra_members_name_what_a_client_can_act_on() -> None:
    assert map_portal_error(ActionRequiredInPortal("OKCuenta")).extra == {
        "interstitial": "OKCuenta"
    }
    assert map_portal_error(BreakerOpen(SINCE, "mfa_required")).extra == {
        "since": SINCE,
        "cause": "mfa_required",
    }
    assert map_portal_error(Denied("send", "writes_disabled")).extra == {
        "reason": "writes_disabled"
    }
    assert map_portal_error(InvalidCredentials("wrong")).extra == {}


def test_a_denial_of_the_servers_own_rules_names_no_reason_to_the_client() -> None:
    assert map_portal_error(Denied("call", "not_on_allowlist")).extra == {}
    assert map_portal_error(Denied("call", "never_call")).extra == {}


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 413, 422, 429, 500, 502, 503, 504])
def test_titles_do_not_depend_on_the_python_version(status: int) -> None:
    assert title_of(status) in {
        "Bad Request",
        "Unauthorized",
        "Forbidden",
        "Not Found",
        "Method Not Allowed",
        "Content Too Large",
        "Unprocessable Content",
        "Too Many Requests",
        "Internal Server Error",
        "Bad Gateway",
        "Service Unavailable",
        "Gateway Timeout",
    }


def test_a_status_without_a_pinned_title_still_gets_one() -> None:
    assert title_of(410) == "Gone"
    assert title_of(799) == "Error"


def raising(error: BaseException) -> object:
    async def fail(*_arguments: object, **_keywords: object) -> NoReturn:
        raise error

    return fail


async def test_a_reply_that_changed_shape_never_shows_its_sample(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = PortalError(SchemaDrift("WSHome.Tracking", "<p>SAMPLE-OF-A-PORTAL-PAGE</p>"))
    monkeypatch.setattr(AccountRuntime, "directory", raising(error))
    response = await api.get("/v1/accounts/marta/children")
    body = problem_of(response, status=502, code="portal_changed")
    assert "WSHome.Tracking" in body["detail"]
    assert "SAMPLE-OF-A-PORTAL-PAGE" not in response.text


async def test_an_unexpected_exception_is_a_500_that_does_not_show_its_message(
    api: Api, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(AccountRuntime, "directory", raising(RuntimeError("do not show this")))
    with caplog.at_level(logging.ERROR, logger="alexia_api.error"):
        response = await api.get("/v1/accounts/marta/children")
    problem_of(response, status=500, code="internal_error")
    assert "do not show this" not in response.text
    [record] = [record for record in caplog.records if record.name == "alexia_api.error"]
    assert record.__dict__["request_id"] == response.headers["x-request-id"]
    assert "do not show this" not in record.getMessage()


async def test_a_500_carries_the_same_protective_headers_as_any_other_answer(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(AccountRuntime, "directory", raising(RuntimeError("x")))
    failed = await api.get("/v1/accounts/marta/children")
    worked = await api.get("/v1/accounts")
    protective = ("x-content-type-options", "referrer-policy", "content-security-policy")
    for name in protective:
        assert failed.headers[name] == worked.headers[name]


async def test_validation_errors_say_where_and_never_echo_the_input(api: Api) -> None:
    response = await api.get("/v1/accounts/marta/children?fresh=maybe")
    body = problem_of(response, status=422, code="validation_error")
    [problem] = body["errors"]
    assert problem["location"] == ["query", "fresh"]
    assert isinstance(problem["message"], str)
    assert "maybe" not in response.text


async def test_an_unknown_address_is_a_not_found_problem(api: Api) -> None:
    response = await api.client.get("/nowhere")
    problem_of(response, status=404, code="not_found")


async def test_a_wrong_method_is_a_problem_that_lists_the_allowed_ones(api: Api) -> None:
    response = await api.client.post("/healthz")
    problem_of(response, status=405, code="method_not_allowed")
    assert response.headers["allow"] == "GET"


async def test_an_account_name_that_cannot_exist_is_the_same_not_found(api: Api) -> None:
    for name in ("Not%20Valid", "nobody"):
        response = await api.get(f"/v1/accounts/{name}")
        problem_of(response, status=404, code="account_not_found")


async def test_a_long_reference_is_cut_before_it_is_echoed(api: Api) -> None:
    response = await api.get(f"/v1/accounts/marta/children/{'x' * 200}")
    body = problem_of(response, status=404, code="child_not_found")
    assert "x" * 80 + "..." in body["detail"]
    assert "x" * 81 not in body["detail"]
