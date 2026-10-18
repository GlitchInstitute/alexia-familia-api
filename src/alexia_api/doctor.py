"""Checks that say why a server would not start or would not work, and what to do about it.

Each finding says what was found and, when it is a problem, the next step. Nothing here prints a
secret. A secret is named by the variable or the file it comes from. The offline checks stay on
this machine. The online check opens each portal's login page, as a browser does, and sends no
credentials, so it cannot lock an account.
"""

import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urlsplit

from pydantic import SecretStr

from alexia_api.config import (
    AccountSettings,
    ConfigError,
    FromEnvironment,
    FromFile,
    Settings,
    WrittenHere,
    find_config_file,
    load_settings,
    read_account_secrets,
    secret_source,
)
from alexia_api.domain.errors import (
    BREAKER_CAUSE_TEXT,
    BreakerCause,
    PortalError,
    PortalMaintenance,
    Transport,
    UnexpectedReply,
    describe,
)
from alexia_api.domain.ids import parse_account_id
from alexia_api.portal.breaker import BREAKER_DIRECTORY, BreakerStore
from alexia_api.portal.login import check_login_page
from alexia_api.portal.session import PortalSession
from alexia_api.services.health import state_dir_writable
from alexia_api.services.keys import FILE_NAME, ApiKeyStore, KeyStoreError
from alexia_api.services.registry import TransportFactory

type Level = Literal["ok", "warn", "fail", "stop"]
"""How much a finding matters.

`ok` needs nothing. `warn` works but is risky or untidy. `fail` lets the server start but leaves
something it needs broken, such as having no API key, which an operator may fix in a running
container. `stop` means the server cannot start until a person fixes it.
"""

_EXAMPLE_TOP_LEVEL_NAMES: Final = frozenset({"test", "example", "invalid"})
_EXAMPLE_DOMAINS: Final = frozenset({"example.com", "example.net", "example.org"})

HOW_TO_UNBLOCK: Final[Mapping[BreakerCause, str]] = {
    "invalid_credentials": "correct the user name or the password, and check that they work in a "
    "browser",
    "refused_login": "sign in with a browser to see what the portal says, then correct the cause",
    "mfa_required": "ask the school whether this login can be used without the multifactor step, "
    "because this server cannot enter a PIN",
    "action_required_in_portal": "sign in once with a browser and finish the step the portal asks "
    "for",
    "state_unreadable": "look at the files in the breaker folder of the state directory and remove "
    "the unreadable one",
}


@dataclass(frozen=True, slots=True)
class Finding:
    level: Level
    subject: str
    message: str
    fix: str | None = None


@dataclass(frozen=True, slots=True)
class Diagnosis:
    findings: tuple[Finding, ...]
    settings: Settings | None

    @property
    def failed(self) -> bool:
        """Something needs a person's attention, whether or not the server can start."""
        return any(finding.level in {"fail", "stop"} for finding in self.findings)

    @property
    def blocked(self) -> bool:
        """The server cannot start until a person fixes something."""
        return any(finding.level == "stop" for finding in self.findings)


def diagnose(config_file: Path | None, environ: Mapping[str, str]) -> Diagnosis:
    """Check the configuration and the files next to it. Nothing here calls a portal."""
    try:
        found = config_file or find_config_file(environ)
        settings = load_settings(found)
    except ConfigError as error:
        return Diagnosis(
            (Finding("stop", "config", str(error), "fix what is named above and run this again"),),
            None,
        )
    findings = [_where_it_was_read(found), *_accounts(settings, environ)]
    findings.append(_state_directory(settings))
    findings.extend(_keys(settings))
    findings.extend(_cautions(settings))
    return Diagnosis(tuple(findings), settings)


async def probe_portals(
    settings: Settings, *, transport_for: TransportFactory | None = None
) -> tuple[Finding, ...]:
    """Open each portal's login page and report whether it answers like the portal."""
    findings = []
    for name, account in settings.accounts.items():
        transport = transport_for(account) if transport_for is not None else None
        session = PortalSession(
            account.base_url,
            transport=transport,
            min_spacing=settings.min_spacing_seconds,
            timeout=settings.request_timeout_seconds,
        )
        subject = f"portal.{name}"
        started = time.perf_counter()
        try:
            await check_login_page(session, account.key)
        except PortalError as error:
            findings.append(Finding("fail", subject, describe(error.detail), _online_fix(error)))
        else:
            milliseconds = round((time.perf_counter() - started) * 1000)
            findings.append(Finding("ok", subject, f"the login page answers in {milliseconds} ms"))
        finally:
            await session.aclose()
    return tuple(findings)


def _online_fix(error: PortalError) -> str | None:
    match error.detail:
        case Transport():
            return "check the portal address and that this machine can reach it"
        case PortalMaintenance():
            return "the portal is down for maintenance, try again later"
        case UnexpectedReply():
            return "check that login_url or portal_url is the portal's own login page"
        case _:
            return None


def _where_it_was_read(found: Path | None) -> Finding:
    if found is None:
        return Finding("ok", "config", "no file found, the settings come from the environment")
    return Finding("ok", "config", f"read {found}")


def _accounts(settings: Settings, environ: Mapping[str, str]) -> list[Finding]:
    if not settings.accounts:
        return [
            Finding(
                "stop",
                "accounts",
                "no account is configured",
                "run `alexia-api init` to write a starter file, or try `alexia-api demo` first",
            )
        ]
    names = ", ".join(settings.accounts)
    findings = [Finding("ok", "accounts", f"{len(settings.accounts)} configured, {names}")]
    breakers = BreakerStore(settings.state_dir / BREAKER_DIRECTORY)
    for name, account in settings.accounts.items():
        findings.extend(_account(name, account, environ, breakers))
    return findings


def _account(
    name: str, account: AccountSettings, environ: Mapping[str, str], breakers: BreakerStore
) -> list[Finding]:
    subject = f"accounts.{name}"
    findings = [_portal(subject, account)]
    try:
        read_account_secrets(name, account, environ)
    except ConfigError as error:
        findings.extend(
            Finding("stop", subject, line, "set the variable or fix the file and run this again")
            for line in str(error).splitlines()
        )
    else:
        where = (
            f"user name from {_source(account.username)}, password from {_source(account.password)}"
        )
        findings.append(Finding("ok", subject, where))
        if isinstance(secret_source(account.password), WrittenHere):
            findings.append(
                Finding(
                    "warn",
                    subject,
                    "the password is written in the configuration file",
                    "use env:NAME or file:/path instead, so that the file holds no secret",
                )
            )
    blocked = breakers.read(parse_account_id(name))
    if blocked is not None:
        findings.append(
            Finding(
                "fail",
                subject,
                f"logins are paused since {blocked.since:%Y-%m-%d %H:%M %z} because "
                f"{BREAKER_CAUSE_TEXT[blocked.cause]}",
                f"{HOW_TO_UNBLOCK[blocked.cause]}, then run `alexia-api accounts reset {name}`",
            )
        )
    return findings


def _is_reserved_for_examples(host: str) -> bool:
    labels = host.split(".")
    return labels[-1] in _EXAMPLE_TOP_LEVEL_NAMES or ".".join(labels[-2:]) in _EXAMPLE_DOMAINS


def _portal(subject: str, account: AccountSettings) -> Finding:
    host = urlsplit(account.base_url).hostname or ""
    if _is_reserved_for_examples(host):
        return Finding(
            "fail",
            subject,
            f"the portal address is still the example {host}",
            "paste the address of your school's login page into login_url",
        )
    return Finding("ok", subject, f"portal {account.base_url}")


def _source(reference: SecretStr) -> str:
    match secret_source(reference):
        case FromEnvironment(name=name):
            return f"the variable {name}"
        case FromFile(path=path):
            return f"the file {path}"
        case WrittenHere():
            return "the configuration file"


def _state_directory(settings: Settings) -> Finding:
    directory = settings.state_dir
    if not state_dir_writable(directory):
        return Finding(
            "stop",
            "state",
            f"{directory} cannot be written",
            "make it writable for the user that runs the server, or set state_dir elsewhere",
        )
    if directory.is_dir():
        return Finding("ok", "state", f"{directory} can be written")
    return Finding("ok", "state", f"{directory} does not exist yet and will be made")


def _keys(settings: Settings) -> list[Finding]:
    try:
        records = ApiKeyStore(settings.state_dir / FILE_NAME).records()
    except KeyStoreError as error:
        return [Finding("fail", "keys", str(error))]
    if not records:
        return [
            Finding(
                "fail",
                "keys",
                "no API key exists, so every request would be refused",
                "run `alexia-api keys create NAME`",
            )
        ]
    names = ", ".join(record.name for record in records)
    findings = [Finding("ok", "keys", f"{len(records)} configured, {names}")]
    findings.extend(
        Finding(
            "warn",
            "keys",
            f"the key {record.name} names the account {account}, which is not configured",
            f"revoke it with `alexia-api keys revoke {record.name}` or add the account",
        )
        for record in records
        for account in record.accounts
        if account != "*" and account not in settings.accounts
    )
    return findings


def _cautions(settings: Settings) -> list[Finding]:
    findings = []
    on = [
        name
        for name, enabled in (
            ("writes", settings.allow_writes),
            ("forms", settings.allow_forms),
            ("restore_unread", settings.restore_unread),
        )
        if enabled
    ]
    if on:
        findings.append(
            Finding(
                "warn",
                "writes",
                f"switched on, {', '.join(on)}, so a key with the write scope can act as you",
                "keep these off unless you need them",
            )
        )
    if settings.rate_limit_per_minute == 0:
        findings.append(
            Finding(
                "warn",
                "rate_limit",
                "the limit on requests for each key is off",
                "set rate_limit_per_minute to a number such as 120",
            )
        )
    if "*" in settings.cors_origins:
        findings.append(
            Finding(
                "warn",
                "cors",
                "a web page from any origin may call the API from a browser",
                "list the exact origins in cors_origins",
            )
        )
    return findings
