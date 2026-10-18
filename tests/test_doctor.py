"""The doctor tells a person what is wrong and what to do, and it never prints a secret."""

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import httpx
import pytest
from pydantic import SecretStr

from alexia_api.config import AccountSettings, FixedSettings
from alexia_api.doctor import HOW_TO_UNBLOCK, Diagnosis, Finding, diagnose, probe_portals
from alexia_api.domain.errors import BREAKER_CAUSE_TEXT, BreakerCause, NoRole, PortalError, describe
from alexia_api.portal.session import PortalSession
from alexia_api.services.keys import FILE_NAME
from tests.harness import Harness
from tests.workspace import ENVIRON, HEALTHY_ACCOUNT, block, make_key, write_config

cannot_deny_access = sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0)


def about(diagnosis: Diagnosis, subject: str) -> list[Finding]:
    return [finding for finding in diagnosis.findings if finding.subject == subject]


def everything_said(findings: tuple[Finding, ...]) -> str:
    return "\n".join(f"{f.subject} {f.message} {f.fix or ''}" for f in findings)


def test_a_healthy_setup_has_nothing_to_report(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    make_key(tmp_path)

    diagnosis = diagnose(path, ENVIRON)

    assert not diagnosis.failed
    assert not diagnosis.blocked
    assert {finding.level for finding in diagnosis.findings} == {"ok"}
    assert [(finding.subject, finding.message) for finding in diagnosis.findings] == [
        ("config", f"read {path}"),
        ("accounts", "1 configured, marta"),
        ("accounts.marta", "portal http://localhost:8081"),
        (
            "accounts.marta",
            "user name from the variable MARTA_USER, password from the variable MARTA_PASSWORD",
        ),
        ("state", f"{tmp_path / 'state'} can be written"),
        ("keys", "1 configured, phone"),
    ]


def test_nothing_configured_says_what_to_do_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    diagnosis = diagnose(None, {})

    assert diagnosis.failed
    assert diagnosis.blocked
    assert diagnosis.findings[0] == Finding(
        "ok", "config", "no file found, the settings come from the environment"
    )
    [accounts] = about(diagnosis, "accounts")
    assert accounts.level == "stop"
    assert accounts.fix is not None
    assert "alexia-api init" in accounts.fix
    assert [finding.message for finding in about(diagnosis, "keys")] == [
        "no API key exists, so every request would be refused"
    ]


def test_the_file_can_be_named_by_a_variable_and_not_only_by_an_argument(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    make_key(tmp_path)

    diagnosis = diagnose(None, {**ENVIRON, "ALEXIA_API_CONFIG": str(path)})

    assert diagnosis.findings[0] == Finding("ok", "config", f"read {path}")


def test_a_file_given_as_an_argument_wins_over_the_variable(tmp_path: Path) -> None:
    (tmp_path / "given").mkdir()
    (tmp_path / "named").mkdir()
    given = write_config(tmp_path / "given")
    named = write_config(tmp_path / "named")

    diagnosis = diagnose(given, {"ALEXIA_API_CONFIG": str(named)})

    assert diagnosis.findings[0] == Finding("ok", "config", f"read {given}")


def test_several_accounts_and_keys_are_listed_in_order(tmp_path: Path) -> None:
    second = HEALTHY_ACCOUNT.replace("accounts.marta", "accounts.pablo").replace("MARTA", "PABLO")
    path = write_config(tmp_path, account=HEALTHY_ACCOUNT + second)
    make_key(tmp_path, "phone")
    make_key(tmp_path, "tablet", accounts=("pablo",))
    environ = {**ENVIRON, "PABLO_USER": "pablo.prueba", "PABLO_PASSWORD": "demo-password-b"}

    diagnosis = diagnose(path, environ)

    assert not diagnosis.failed
    assert [f.message for f in about(diagnosis, "accounts")] == ["2 configured, marta, pablo"]
    assert [f.message for f in about(diagnosis, "keys")] == ["2 configured, phone, tablet"]


def test_a_wrong_file_variable_stops_the_server_with_one_finding(tmp_path: Path) -> None:
    diagnosis = diagnose(None, {"ALEXIA_API_CONFIG": str(tmp_path / "missing.toml")})

    assert diagnosis.settings is None
    assert diagnosis.blocked
    assert diagnosis.failed
    [finding] = diagnosis.findings
    assert (finding.level, finding.subject) == ("stop", "config")
    assert "missing.toml" in finding.message


def test_a_misspelled_setting_stops_the_server_and_is_named(tmp_path: Path) -> None:
    path = write_config(tmp_path, top="allow_wrties = true")

    diagnosis = diagnose(path, ENVIRON)

    assert diagnosis.settings is None
    [finding] = diagnosis.findings
    assert (finding.level, finding.subject) == ("stop", "config")
    assert "allow_wrties" in finding.message
    assert finding.fix is not None


def test_every_secret_that_cannot_be_read_stops_the_server_on_its_own_line(
    tmp_path: Path,
) -> None:
    path = write_config(tmp_path)
    make_key(tmp_path)

    diagnosis = diagnose(path, {})

    stops = [f for f in about(diagnosis, "accounts.marta") if f.level == "stop"]
    assert [stop.message for stop in stops] == [
        "accounts.marta.username refers to the environment variable MARTA_USER, which is not set",
        (
            "accounts.marta.password refers to the environment variable MARTA_PASSWORD, "
            "which is not set"
        ),
    ]
    assert all(stop.fix is not None for stop in stops)
    assert diagnosis.blocked
    assert [f.subject for f in diagnosis.findings][-2:] == ["state", "keys"]


def test_a_secret_in_a_file_is_named_by_the_file(tmp_path: Path) -> None:
    secret_file = tmp_path / "marta-password"
    secret_file.write_text("pw-from-a-file\n", encoding="utf-8")
    account = HEALTHY_ACCOUNT.replace("env:MARTA_PASSWORD", f"file:{secret_file.as_posix()}")
    path = write_config(tmp_path, account=account)

    diagnosis = diagnose(path, ENVIRON)

    [where] = [f for f in about(diagnosis, "accounts.marta") if f.message.startswith("user name")]
    assert where.message == (
        f"user name from the variable MARTA_USER, password from the file {secret_file.as_posix()}"
    )
    assert {finding.level for finding in about(diagnosis, "accounts.marta")} == {"ok"}
    assert "pw-from-a-file" not in everything_said(diagnosis.findings)


def test_a_password_written_in_the_file_is_a_warning_and_is_never_shown(tmp_path: Path) -> None:
    account = HEALTHY_ACCOUNT.replace('"env:MARTA_PASSWORD"', '"hunter2-secret"')
    path = write_config(tmp_path, account=account)
    make_key(tmp_path)

    diagnosis = diagnose(path, {"MARTA_USER": "marta.ejemplo"})

    assert not diagnosis.failed
    [warning] = [f for f in diagnosis.findings if f.level == "warn"]
    assert warning.message == "the password is written in the configuration file"
    assert warning.fix is not None
    assert "env:NAME" in warning.fix
    assert "hunter2-secret" not in everything_said(diagnosis.findings)
    assert "marta.ejemplo" not in everything_said(diagnosis.findings)


def test_a_user_name_written_in_the_file_is_not_a_warning(tmp_path: Path) -> None:
    account = HEALTHY_ACCOUNT.replace('"env:MARTA_USER"', '"marta.ejemplo"')
    path = write_config(tmp_path, account=account)
    make_key(tmp_path)

    diagnosis = diagnose(path, {"MARTA_PASSWORD": "demo-password-a"})

    assert {finding.level for finding in diagnosis.findings} == {"ok"}


@pytest.mark.parametrize(
    "address",
    [
        "https://portal.example.test",
        "https://portal.invalid",
        "https://school.example",
        "https://example.com",
        "https://portal.example.net",
        "https://portal.example.org",
    ],
)
def test_an_address_reserved_for_examples_is_a_failure(tmp_path: Path, address: str) -> None:
    account = HEALTHY_ACCOUNT.replace("http://localhost:8081", address)
    path = write_config(tmp_path, account=account)

    diagnosis = diagnose(path, ENVIRON)

    [portal] = [f for f in about(diagnosis, "accounts.marta") if "address" in f.message]
    assert portal.level == "fail"
    assert "still the example" in portal.message
    assert portal.fix is not None
    assert "login_url" in portal.fix


def test_a_real_looking_address_passes(tmp_path: Path) -> None:
    account = HEALTHY_ACCOUNT.replace("http://localhost:8081", "https://portal.myschool.es")
    path = write_config(tmp_path, account=account)

    diagnosis = diagnose(path, ENVIRON)

    assert about(diagnosis, "accounts.marta")[0] == Finding(
        "ok", "accounts.marta", "portal https://portal.myschool.es"
    )


@pytest.mark.parametrize("cause", get_args(BreakerCause))
def test_a_paused_account_says_why_and_how_to_resume(tmp_path: Path, cause: BreakerCause) -> None:
    path = write_config(tmp_path)
    make_key(tmp_path)
    block(tmp_path, cause)

    diagnosis = diagnose(path, ENVIRON)

    [paused] = [f for f in about(diagnosis, "accounts.marta") if f.level == "fail"]
    assert paused.message == (
        f"logins are paused since 2026-10-18 20:15 +0000 because {BREAKER_CAUSE_TEXT[cause]}"
    )
    assert paused.fix == f"{HOW_TO_UNBLOCK[cause]}, then run `alexia-api accounts reset marta`"


def test_every_cause_of_a_pause_has_advice() -> None:
    assert set(HOW_TO_UNBLOCK) == set(get_args(BreakerCause))


def test_a_pause_and_a_missing_key_fail_the_check_but_do_not_stop_the_server(
    tmp_path: Path,
) -> None:
    path = write_config(tmp_path)
    block(tmp_path, "invalid_credentials")

    diagnosis = diagnose(path, ENVIRON)

    assert {finding.level for finding in diagnosis.findings} == {"ok", "fail"}
    assert diagnosis.failed
    assert not diagnosis.blocked


def test_a_state_directory_that_does_not_exist_yet_is_fine(tmp_path: Path) -> None:
    diagnosis = diagnose(write_config(tmp_path), ENVIRON)

    [state] = about(diagnosis, "state")
    assert state == Finding(
        "ok", "state", f"{tmp_path / 'state'} does not exist yet and will be made"
    )


@pytest.mark.skipif(cannot_deny_access, reason="this account can write anywhere")
def test_a_state_directory_that_cannot_be_written_stops_the_server(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    path = write_config(tmp_path, state=locked / "state")
    locked.chmod(0o500)
    try:
        diagnosis = diagnose(path, ENVIRON)
    finally:
        locked.chmod(0o700)

    [state] = about(diagnosis, "state")
    assert state.level == "stop"
    assert diagnosis.blocked
    assert "cannot be written" in state.message
    assert state.fix is not None
    assert "state_dir" in state.fix


def test_a_key_file_that_cannot_be_read_is_a_failure(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / FILE_NAME).write_text("{not json", encoding="utf-8")

    diagnosis = diagnose(path, ENVIRON)

    [keys] = about(diagnosis, "keys")
    assert keys.level == "fail"
    assert keys.message == f"{FILE_NAME} cannot be read, fix or remove the file first"


def test_no_key_at_all_is_a_failure_with_the_command_to_run(tmp_path: Path) -> None:
    diagnosis = diagnose(write_config(tmp_path), ENVIRON)

    [keys] = about(diagnosis, "keys")
    assert keys.level == "fail"
    assert keys.fix == "run `alexia-api keys create NAME`"


def test_a_key_for_an_account_that_is_not_configured_is_a_warning(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    make_key(tmp_path, "phone")
    make_key(tmp_path, "ghost", accounts=("pablo", "marta"))

    diagnosis = diagnose(path, ENVIRON)

    assert not diagnosis.failed
    [warning] = [f for f in about(diagnosis, "keys") if f.level == "warn"]
    assert warning.message == "the key ghost names the account pablo, which is not configured"
    assert warning.fix == "revoke it with `alexia-api keys revoke ghost` or add the account"


def test_switched_on_writes_are_a_warning_that_lists_what_is_on(tmp_path: Path) -> None:
    path = write_config(tmp_path, top="allow_writes = true\nallow_forms = true")
    make_key(tmp_path)

    diagnosis = diagnose(path, ENVIRON)

    assert not diagnosis.failed
    [writes] = about(diagnosis, "writes")
    assert writes.level == "warn"
    assert (
        writes.message == "switched on, writes, forms, so a key with the write scope can act as you"
    )


@pytest.mark.parametrize(
    ("setting", "named"),
    [
        ("allow_writes = true", "writes"),
        ("restore_unread = true", "restore_unread"),
        ("allow_writes = true\nrestore_unread = true", "writes, restore_unread"),
    ],
)
def test_the_switches_that_are_on_are_named_and_the_others_are_not(
    tmp_path: Path, setting: str, named: str
) -> None:
    path = write_config(tmp_path, top=setting)
    make_key(tmp_path)

    [writes] = about(diagnose(path, ENVIRON), "writes")

    assert writes.message == f"switched on, {named}, so a key with the write scope can act as you"


def test_forms_without_writes_stops_the_server_as_a_configuration_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, top="allow_forms = true")

    diagnosis = diagnose(path, ENVIRON)

    [finding] = diagnosis.findings
    assert (finding.level, finding.subject) == ("stop", "config")
    assert "allow_forms needs allow_writes" in finding.message


def test_no_rate_limit_is_a_warning(tmp_path: Path) -> None:
    path = write_config(tmp_path, top="rate_limit_per_minute = 0")
    make_key(tmp_path)

    [limit] = about(diagnose(path, ENVIRON), "rate_limit")

    assert limit.level == "warn"
    assert limit.fix is not None
    assert "rate_limit_per_minute" in limit.fix


def test_any_origin_in_cors_is_a_warning(tmp_path: Path) -> None:
    path = write_config(tmp_path, top='cors_origins = ["*"]')
    make_key(tmp_path)

    [cors] = about(diagnose(path, ENVIRON), "cors")

    assert cors.level == "warn"
    assert cors.fix == "list the exact origins in cors_origins"


def test_a_listed_origin_and_the_defaults_raise_no_warning(tmp_path: Path) -> None:
    path = write_config(tmp_path, top='cors_origins = ["https://app.example.test"]')
    make_key(tmp_path)

    diagnosis = diagnose(path, ENVIRON)

    assert {finding.level for finding in diagnosis.findings} == {"ok"}


def test_no_finding_ever_holds_a_secret_whatever_is_wrong(tmp_path: Path) -> None:
    secret = "never-print-this-9f3c"
    account = HEALTHY_ACCOUNT.replace('"env:MARTA_PASSWORD"', f'"{secret}"')
    path = write_config(tmp_path, top="rate_limit_per_minute = 0", account=account)
    block(tmp_path, "invalid_credentials")

    diagnosis = diagnose(path, {"MARTA_USER": secret})

    assert secret not in everything_said(diagnosis.findings)


def settings_for(portal: str) -> FixedSettings:
    return FixedSettings(
        accounts={
            "marta": AccountSettings(
                portal_url=portal,
                institution_key="demo-school",
                username=SecretStr("marta.ejemplo"),
                password=SecretStr("demo-password-a"),
            )
        }
    )


async def test_the_portals_that_answer_are_reported_one_by_one(harness: Harness) -> None:
    findings = await probe_portals(
        harness.settings(), transport_for=lambda _account: harness.sim.transport()
    )

    assert [(finding.level, finding.subject) for finding in findings] == [
        ("ok", "portal.marta"),
        ("ok", "portal.pablo"),
    ]
    assert all(re.fullmatch(r"the login page answers in \d+ ms", f.message) for f in findings)


async def test_the_time_a_portal_takes_is_reported_in_milliseconds(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = iter([10.0, 10.25, 20.0, 20.5])
    monkeypatch.setattr("alexia_api.doctor.time", SimpleNamespace(perf_counter=lambda: next(ticks)))

    findings = await probe_portals(
        harness.settings(), transport_for=lambda _account: harness.sim.transport()
    )

    assert [finding.message for finding in findings] == [
        "the login page answers in 250 ms",
        "the login page answers in 500 ms",
    ]


async def test_probing_a_portal_sends_no_credentials(harness: Harness) -> None:
    await probe_portals(harness.settings(), transport_for=lambda _account: harness.sim.transport())

    assert {request.path for request in harness.sim.requests} == {"/ACWeb/LogOn.aspx"}
    assert harness.sim.counters.login_attempts == 0


async def test_a_portal_in_maintenance_is_reported_with_advice(harness: Harness) -> None:
    harness.sim.options.maintenance = "http503"

    [finding, _] = await probe_portals(
        harness.settings(), transport_for=lambda _account: harness.sim.transport()
    )

    assert (finding.level, finding.subject) == ("fail", "portal.marta")
    assert "maintenance" in finding.message
    assert finding.fix == "the portal is down for maintenance, try again later"


async def test_a_portal_that_cannot_be_reached_is_reported_with_advice() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    [finding] = await probe_portals(
        settings_for("https://portal.example.test"),
        transport_for=lambda _account: httpx.MockTransport(refuse),
    )

    assert (finding.level, finding.subject) == ("fail", "portal.marta")
    assert finding.fix == "check the portal address and that this machine can reach it"


async def test_a_web_page_that_is_not_the_portal_is_reported_with_advice() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, html="<html>Hello</html>"))

    [finding] = await probe_portals(
        settings_for("https://portal.example.test"), transport_for=lambda _account: transport
    )

    assert finding.level == "fail"
    assert finding.fix == "check that login_url or portal_url is the portal's own login page"


async def test_a_login_page_that_is_missing_gets_the_advice_for_a_wrong_address() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(404, html="<html></html>"))

    [finding] = await probe_portals(
        settings_for("https://portal.myschool.es"), transport_for=lambda _account: transport
    )

    assert finding.level == "fail"
    assert finding.fix == "check that login_url or portal_url is the portal's own login page"


async def test_a_failure_without_advice_still_says_what_happened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refuse(_session: PortalSession, _institution_key: str) -> None:
        raise PortalError(NoRole())

    monkeypatch.setattr("alexia_api.doctor.check_login_page", refuse)

    [finding] = await probe_portals(settings_for("https://portal.myschool.es"))

    assert finding == Finding("fail", "portal.marta", describe(NoRole()))


async def test_every_session_is_closed_even_when_the_portal_fails(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[PortalSession] = []
    close = PortalSession.aclose

    async def spy(self: PortalSession) -> None:
        closed.append(self)
        await close(self)

    monkeypatch.setattr(PortalSession, "aclose", spy)
    harness.sim.options.maintenance = "http503"

    findings = await probe_portals(
        harness.settings(), transport_for=lambda _account: harness.sim.transport()
    )

    assert [finding.level for finding in findings] == ["fail", "fail"]
    assert len(closed) == 2


async def test_no_accounts_means_nothing_to_probe() -> None:
    assert await probe_portals(FixedSettings()) == ()
