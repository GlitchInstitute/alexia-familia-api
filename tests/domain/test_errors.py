import re
from datetime import UTC, datetime
from typing import get_args

import pytest

from alexia_api.domain.errors import (
    BREAKER_CAUSE_TEXT,
    MAX_DRIFT_SAMPLE_CHARS,
    ActionRequiredInPortal,
    AttachmentTooLarge,
    BreakerCause,
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
    breaker_cause,
    describe,
    detail_of,
    sample_of,
)

EXAMPLES: list[PortalErrorDetail] = [
    NoCredentials(),
    InvalidCredentials(portal_text="Usuario o código de acceso incorrecto"),
    RefusedLogin(portal_text="Algo salió mal"),
    MfaRequired(),
    ActionRequiredInPortal(interstitial="TxtLegales"),
    RoleChoiceRequired(role_count=2),
    NoRole(),
    PortalMaintenance(status=503),
    TokenInvalid(),
    PortalFault(portal_text="Referencia a objeto no establecida como instancia de un objeto."),
    WsRejected(call="WSHome.GetWPSeguimiento", status=500),
    SessionExpired(),
    UnexpectedReply(where="login"),
    SchemaDrift(where="inbox row", sample="<html></html>"),
    Transport(reason="timeout"),
    AttachmentTooLarge(limit=25 * 1024 * 1024),
    Denied(call="WSComunicados.Enviar", reason="writes_disabled"),
    ComposeRejected(call="WSComunicados.Enviar", portal_text="No se pudo enviar", portal_code=None),
    ComposeMismatch(where="subject"),
    BreakerOpen(since=datetime(2026, 1, 1, tzinfo=UTC), cause="invalid_credentials"),
]
ACCOUNT_LOCKING = {
    "invalid_credentials",
    "refused_login",
    "mfa_required",
    "action_required_in_portal",
}


def test_the_examples_cover_every_failure() -> None:
    assert {type(example) for example in EXAMPLES} == set(get_args(PortalErrorDetail.__value__))


def test_every_failure_has_its_own_snake_case_code() -> None:
    codes = [example.code for example in EXAMPLES]

    assert len(set(codes)) == len(codes)
    assert all(re.fullmatch(r"[a-z]+(?:_[a-z]+)*", code) for code in codes)


@pytest.mark.parametrize("detail", EXAMPLES, ids=lambda detail: type(detail).__name__)
def test_every_failure_describes_itself_in_one_plain_line(detail: PortalErrorDetail) -> None:
    text = describe(detail)

    assert text
    assert "\n" not in text


@pytest.mark.parametrize("detail", EXAMPLES, ids=lambda detail: type(detail).__name__)
def test_only_the_failures_that_can_lock_the_account_trip_the_breaker(
    detail: PortalErrorDetail,
) -> None:
    cause = breaker_cause(detail)

    if detail.code in ACCOUNT_LOCKING:
        assert cause == detail.code
    else:
        assert cause is None


def test_failures_that_carry_portal_text_repeat_it() -> None:
    assert "Usuario o código" in describe(InvalidCredentials(portal_text="Usuario o código"))
    assert "Algo salió mal" in describe(RefusedLogin(portal_text="Algo salió mal"))
    assert "fallo interno" in describe(PortalFault(portal_text="fallo interno"))
    assert "No se pudo" in describe(
        ComposeRejected(call="WSX.Y", portal_text="No se pudo", portal_code="E1")
    )


def test_a_denial_names_the_switch_that_allows_it() -> None:
    writes = describe(Denied(call="WSX.Y", reason="writes_disabled"))
    forms = describe(Denied(call="WSX.Y", reason="forms_disabled"))
    unread = describe(Denied(call="WSX.Y", reason="unread_restore_disabled"))
    other = describe(Denied(call="WSX.Y", reason="never_call"))

    assert "ALEXIA_API_ALLOW_WRITES" in writes
    assert "ALEXIA_API_ALLOW_FORMS" in forms
    assert "ALEXIA_API_RESTORE_UNREAD" in unread
    assert "never_call" in other


def test_a_file_that_is_too_large_names_the_limit_and_the_setting_that_raises_it() -> None:
    text = describe(AttachmentTooLarge(limit=40 * 1024 * 1024))

    assert "40 MiB" in text
    assert "ALEXIA_API_MAX_ATTACHMENT_MIB" in text
    assert "portal" in text


def test_every_breaker_cause_has_a_plain_description() -> None:
    assert set(BREAKER_CAUSE_TEXT) == set(get_args(BreakerCause))
    for cause in get_args(BreakerCause):
        text = describe(BreakerOpen(since=datetime(2026, 1, 1, tzinfo=UTC), cause=cause))
        assert BREAKER_CAUSE_TEXT[cause] in text


def test_a_portal_error_carries_its_detail_and_its_description() -> None:
    detail = WsRejected(call="WSX.Y", status=500)
    error = PortalError(detail)

    assert error.detail is detail
    assert str(error) == describe(detail)
    assert detail_of(error) is detail


def test_any_other_exception_is_reported_as_an_internal_fault() -> None:
    detail = detail_of(KeyError("secret"))

    assert detail == UnexpectedReply(where="internal KeyError")
    assert "secret" not in describe(detail)


def test_drift_samples_are_capped() -> None:
    assert sample_of("abc") == "abc"
    assert len(sample_of("x" * (MAX_DRIFT_SAMPLE_CHARS + 10))) == MAX_DRIFT_SAMPLE_CHARS
