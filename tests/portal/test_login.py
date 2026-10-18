"""Signing in against the simulated portal, one refusal at a time."""

from contextlib import aclosing

import httpx
import pytest

from alexia_api.clock import ManualClock
from alexia_api.domain.errors import (
    ActionRequiredInPortal,
    Interstitial,
    InvalidCredentials,
    MfaRequired,
    NoRole,
    PortalErrorDetail,
    PortalFault,
    PortalMaintenance,
    RefusedLogin,
    RoleChoiceRequired,
    TokenInvalid,
    UnexpectedReply,
)
from alexia_api.domain.ids import RoleId, parse_role_id
from alexia_api.portal.login import LoginOk, check_login_page, classify_refusal, login
from alexia_api.portal.session import PortalSession
from alexia_api.sim.app import (
    BAD_CREDENTIALS_TEXT,
    EXPIRED_LOGON_TEXT,
    FAULT_TEXT,
    LOCKED_TEXT,
)
from alexia_api.sim.world import (
    DEMO_PASSWORD_A,
    DEMO_PASSWORD_B,
    DEMO_USER_A,
    DEMO_USER_B,
    SIM_INSTITUTION_KEY,
    synthetic_guid,
)
from tests.harness import Failure, Harness

INTERSTITIALS: list[Interstitial] = [
    "CambiarPws",
    "TxtLegales",
    "OKCuenta",
    "MatOnline",
    "Classroom",
]


async def sign_in(
    harness: Harness,
    *,
    username: str = DEMO_USER_A,
    password: str = DEMO_PASSWORD_A,
    role_id: RoleId | None = None,
) -> LoginOk:
    credentials = harness.credentials(username, password)
    return await login(harness.session(), credentials, role_id=role_id)


async def test_signs_in_and_reads_the_home_page(harness: Harness) -> None:
    ok = await sign_in(harness)

    assert ok.role_count == 1
    assert ok.role_id == synthetic_guid(0x401)
    assert ok.home.guardian is not None
    assert ok.home.guardian.first_name == "Marta"
    assert [child.first_name for child in ok.home.children] == ["Lucía", "Mateo"]


async def test_the_flow_is_token_password_roles_role_then_home(harness: Harness) -> None:
    await sign_in(harness)

    assert [request.path.rsplit("/", 1)[-1] for request in harness.sim.requests] == [
        "LogOn.aspx",
        "Validar",
        "GetRoles",
        "ValidarRol",
        "HomeMetro.aspx",
    ]
    assert {request.status for request in harness.sim.requests} == {200}


async def test_each_family_sees_only_its_own_children(harness: Harness) -> None:
    ok = await sign_in(harness, username=DEMO_USER_B, password=DEMO_PASSWORD_B)

    assert ok.home.guardian is not None
    assert ok.home.guardian.first_name == "Pablo"
    assert [child.first_name for child in ok.home.children] == ["Hugo", "Alba"]


@pytest.mark.parametrize(
    ("username", "password"),
    [(DEMO_USER_A, "wrong"), ("nobody.here", DEMO_PASSWORD_A)],
)
async def test_a_wrong_login_is_reported_once_and_never_retried(
    harness: Harness, failure: Failure, username: str, password: str
) -> None:
    detail = await failure(sign_in(harness, username=username, password=password))

    assert detail == InvalidCredentials(portal_text=BAD_CREDENTIALS_TEXT)
    assert harness.requests_to("/Validar") == 1
    assert harness.sim.counters.login_attempts == 1


async def test_a_refusal_it_does_not_recognise_is_named_as_such(
    harness: Harness, failure: Failure
) -> None:
    harness.sim.options.lock_after_failures = 0

    detail = await failure(sign_in(harness))

    assert detail == RefusedLogin(portal_text=LOCKED_TEXT)


async def test_a_stale_token_gets_one_fresh_attempt(harness: Harness) -> None:
    harness.sim.counters.token_failures_left = 1

    ok = await sign_in(harness)

    assert ok.role_count == 1
    assert harness.requests_to("/Validar") == 2
    assert harness.requests_to("LogOn.aspx") == 2


async def test_two_stale_tokens_in_a_row_stop_the_login(harness: Harness, failure: Failure) -> None:
    harness.sim.counters.token_failures_left = 2

    detail = await failure(sign_in(harness))

    assert detail == TokenInvalid()
    assert harness.requests_to("/Validar") == 2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (FAULT_TEXT, PortalFault(portal_text=FAULT_TEXT)),
        (
            "Object reference not set to an instance of an object.",
            PortalFault(portal_text="Object reference not set to an instance of an object."),
        ),
        ("Excepción: usuario incorrecto", PortalFault(portal_text="Excepción: usuario incorrecto")),
        (EXPIRED_LOGON_TEXT, TokenInvalid()),
        ("Token inválido", TokenInvalid()),
        (BAD_CREDENTIALS_TEXT, InvalidCredentials(portal_text=BAD_CREDENTIALS_TEXT)),
        ("Contraseña incorrecta", InvalidCredentials(portal_text="Contraseña incorrecta")),
        ("Invalid password", InvalidCredentials(portal_text="Invalid password")),
        ("Credenciales inválidas", InvalidCredentials(portal_text="Credenciales inválidas")),
        (LOCKED_TEXT, RefusedLogin(portal_text=LOCKED_TEXT)),
        ("", RefusedLogin(portal_text="")),
    ],
)
def test_a_refusal_is_named_by_what_the_portal_said(text: str, expected: PortalErrorDetail) -> None:
    assert classify_refusal(text) == expected


async def test_a_multifactor_account_is_named(harness: Harness, failure: Failure) -> None:
    harness.sim.options.multifactor = True

    assert await failure(sign_in(harness)) == MfaRequired()


async def test_several_roles_need_a_choice(harness: Harness, failure: Failure) -> None:
    harness.sim.options.roles = 2

    assert await failure(sign_in(harness)) == RoleChoiceRequired(role_count=2)


async def test_a_chosen_role_is_used(harness: Harness) -> None:
    harness.sim.options.roles = 2
    chosen = parse_role_id(synthetic_guid(0x402))

    ok = await sign_in(harness, role_id=chosen)

    assert (ok.role_id, ok.role_count) == (chosen, 2)


async def test_a_role_that_is_not_offered_is_refused(harness: Harness, failure: Failure) -> None:
    harness.sim.options.roles = 2
    unknown = parse_role_id(synthetic_guid(0x999))

    assert await failure(sign_in(harness, role_id=unknown)) == RoleChoiceRequired(role_count=2)


async def test_a_login_without_roles_is_named(harness: Harness, failure: Failure) -> None:
    harness.sim.options.roles = 0

    assert await failure(sign_in(harness)) == NoRole()


@pytest.mark.parametrize("kind", INTERSTITIALS)
async def test_a_step_that_needs_a_browser_is_named(
    harness: Harness, failure: Failure, kind: Interstitial
) -> None:
    harness.sim.options.interstitial = kind

    assert await failure(sign_in(harness)) == ActionRequiredInPortal(interstitial=kind)


async def test_a_maintenance_page_is_reported(harness: Harness, failure: Failure) -> None:
    harness.sim.options.maintenance = "page"

    assert await failure(sign_in(harness)) == PortalMaintenance(status=200)


async def test_a_503_on_the_logon_page_is_maintenance(harness: Harness, failure: Failure) -> None:
    harness.sim.options.maintenance = "http503"

    assert await failure(sign_in(harness)) == PortalMaintenance(status=503)


async def test_a_home_address_off_the_portal_is_refused(harness: Harness, failure: Failure) -> None:
    harness.sim.options.home_route = "https://elsewhere.invalid/ACWeb/home.aspx"

    detail = await failure(sign_in(harness))

    assert detail == UnexpectedReply(where="RutaHome points off the portal")


@pytest.mark.parametrize(
    ("response", "where"),
    [
        (httpx.Response(200, text="<html>hello</html>"), "logon page has no Token field"),
        (httpx.Response(404, text="gone"), "logon page HTTP 404"),
    ],
)
async def test_an_odd_logon_page_is_unexpected(
    harness: Harness, failure: Failure, response: httpx.Response, where: str
) -> None:
    session = PortalSession(
        "https://portal.test",
        transport=httpx.MockTransport(lambda _request: response),
        clock=ManualClock(),
    )

    async with aclosing(session):
        detail = await failure(login(session, harness.credentials()))

    assert detail == UnexpectedReply(where=where)


def test_credentials_do_not_print_their_secrets(harness: Harness) -> None:
    text = repr(harness.credentials())

    assert DEMO_PASSWORD_A not in text
    assert DEMO_USER_A not in text


async def test_checking_the_login_page_opens_it_and_sends_no_credentials(harness: Harness) -> None:
    await check_login_page(harness.session(), SIM_INSTITUTION_KEY)

    assert [(request.method, request.path) for request in harness.sim.requests] == [
        ("GET", "/ACWeb/LogOn.aspx")
    ]
    assert harness.sim.counters.login_attempts == 0


async def test_checking_the_login_page_reports_a_maintenance_page(
    harness: Harness, failure: Failure
) -> None:
    harness.sim.options.maintenance = "page"

    detail = await failure(check_login_page(harness.session(), SIM_INSTITUTION_KEY))

    assert detail == PortalMaintenance(status=200)


async def test_checking_the_login_page_reports_a_503_as_maintenance(
    harness: Harness, failure: Failure
) -> None:
    harness.sim.options.maintenance = "http503"

    detail = await failure(check_login_page(harness.session(), SIM_INSTITUTION_KEY))

    assert detail == PortalMaintenance(status=503)


async def test_checking_the_login_page_notices_a_page_that_is_not_the_portal(
    failure: Failure,
) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, html="<html><body>Hello</body></html>")
    )
    session = PortalSession("https://portal.example.test", transport=transport)

    async with aclosing(session):
        detail = await failure(check_login_page(session, "demo-school"))

    assert detail == UnexpectedReply(where="logon page has no Token field")
