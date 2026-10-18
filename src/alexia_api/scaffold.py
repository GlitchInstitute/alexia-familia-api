"""The starter configuration file that `alexia-api init` writes.

Every comment comes from the descriptions in `config.py`, and every default from the model,
through `reference.catalog`. Only the account block holds choices of its own, such as the example
address and the names of the secret variables. A setting that has no example there raises an
error, so a new account setting cannot be left out of the starter by accident.
"""

import os
import shlex
import textwrap
from pathlib import Path
from typing import Final, Literal

from pydantic import SecretStr, ValidationError

from alexia_api.config import DEFAULT_CONFIG_NAME, AccountSettings
from alexia_api.domain.ids import InvalidIdError, parse_account_id
from alexia_api.oserrors import why
from alexia_api.reference import NAME_PLACEHOLDER, Section, SettingDoc, catalog, format_value

DEFAULT_ACCOUNT: Final = "family"
EXAMPLE_LOGIN_URL: Final = "https://portal.example.test/ACWeb/LogOn.aspx?key=your-school-key"
EXAMPLE_STUDENT_ID: Final = "5afe0000-0000-4000-8000-000000000101"
ACCOUNT_PATH: Final = ("accounts", NAME_PLACEHOLDER)
WIDTH: Final = 90

HEADER: Final = """\
alexia-familia-api configuration.

A line that starts with # is a comment. The settings below are optional, and each one shows its \
default. Remove the # in front of a setting to change it.

Any setting can also come from an environment variable. Write ALEXIA_API_, then the name in \
capital letters, with two underscores between a table and its setting. For example, \
ALEXIA_API_CACHE__TRACKING=60 sets tracking in the cache table. A variable wins over this file.

Keep passwords out of this file. Name an environment variable or a file that holds them.
"""

TABLE_HINT: Final = (
    "Remove the # in front of the table name too when you change a setting below it."
)

ACCOUNTS_INTRO: Final = """\
One block for each portal login. The name after "accounts." goes into URLs, so use lower case \
letters, digits, and hyphens. One login lists all of a parent's children, so a parent with two \
children needs a single block. Add another block for another parent's login.
"""

type SecretPart = Literal["username", "password"]


class ScaffoldError(Exception):
    """The starter file cannot be made, and the message says what to change."""


def secret_variable(account: str, part: SecretPart) -> str:
    """The name of the environment variable that holds one secret of an account.

    It never starts with `ALEXIA_API_`, because the server refuses those names unless they are
    settings.
    """
    return f"PORTAL_{account.upper().replace('-', '_')}_{part.upper()}"


def render_starter(account: str = DEFAULT_ACCOUNT, login_url: str | None = None) -> str:
    """The text of a starter file with one account, ready to edit."""
    name = _account_name(account)
    address = EXAMPLE_LOGIN_URL if login_url is None else _login_url(login_url)
    sections = catalog()
    accounts = next(section for section in sections if section.path == ACCOUNT_PATH)
    lines = [*_comment(HEADER), ""]
    for section in sections:
        if section is not accounts:
            lines += _table(section)
    lines += _account_block(accounts, name, address)
    return "\n".join(lines).rstrip("\n") + "\n"


def write_starter(path: Path, text: str, *, replace: bool = False) -> None:
    """Write the file. It is readable by its owner only, in case a secret is added to it later."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ScaffoldError(f"{path.parent} cannot be made, {why(error)}") from None
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if replace else os.O_EXCL)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        raise ScaffoldError(f"{path} already exists, add --force to replace it") from None
    except OSError as error:
        raise ScaffoldError(f"{path} cannot be written, {why(error)}") from None
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)


def next_steps(path: Path, account: str, *, has_login_url: bool, windows: bool = False) -> str:
    """What to do after `init`, in order, with the exact commands."""
    hint = "" if path == Path(DEFAULT_CONFIG_NAME) else f" --config {shlex.quote(str(path))}"
    steps: list[str] = []
    if not has_login_url:
        steps.append(
            "Open the file and paste the address of your school's login page into login_url."
        )
    secrets: tuple[tuple[SecretPart, str], ...] = (
        ("username", "your user name"),
        ("password", "your password"),
    )
    steps.append(
        "Put your portal login in the environment, so that no secret is in the file.\n"
        + "\n".join(
            _set_variable(secret_variable(account, part), shown, windows=windows)
            for part, shown in secrets
        )
    )
    steps.append(
        "Make a key for your phone or your program. It is shown once, so copy it.\n"
        f"       alexia-api keys create phone{hint}"
    )
    steps.append(f"Check the setup.\n       alexia-api doctor{hint}")
    steps.append(f"Start the server.\n       alexia-api serve{hint}")
    numbered = "\n".join(f"  {number}. {step}" for number, step in enumerate(steps, start=1))
    return f"Wrote {path} with the account {account}.\n\nNext\n{numbered}"


def _set_variable(name: str, value: str, *, windows: bool) -> str:
    if windows:
        return f"       $env:{name} = '{value}'"
    return f"       export {name}='{value}'"


def _account_name(account: str) -> str:
    try:
        return parse_account_id(account)
    except InvalidIdError:
        raise ScaffoldError(
            f"'{account}' is not a valid account name, use lower case letters, digits, and hyphens"
        ) from None


def _login_url(address: str) -> str:
    cleaned = address.strip()
    try:
        AccountSettings(login_url=cleaned, username=SecretStr("x"), password=SecretStr("x"))
    except ValidationError as error:
        problems = error.errors(include_url=False, include_context=False, include_input=False)
        raise ScaffoldError(problems[0]["msg"].removeprefix("Value error, ")) from None
    return cleaned


def _comment(text: str) -> list[str]:
    lines: list[str] = []
    for index, paragraph in enumerate(text.strip().split("\n\n")):
        if index:
            lines.append("#")
        wrapped = textwrap.wrap(
            " ".join(paragraph.split()),
            width=WIDTH - 2,
            break_long_words=False,
            break_on_hyphens=False,
        )
        lines.extend(f"# {line}" for line in wrapped)
    return lines


def _table(section: Section) -> list[str]:
    """A table, or the top level, with every setting shown at its default and commented out."""
    lines: list[str] = []
    if section.path:
        lines += [
            *_comment(f"{section.description} {TABLE_HINT}"),
            f"# [{'.'.join(section.path)}]",
            "",
        ]
    for setting in section.settings:
        lines += [
            *_comment(setting.explanation),
            f"# {setting.path[-1]} = {format_value(setting.default)}",
            "",
        ]
    return lines


def _account_block(section: Section, name: str, login_url: str) -> list[str]:
    lines = [*_comment(ACCOUNTS_INTRO), f"[accounts.{name}]"]
    tables_last = sorted(section.settings, key=lambda setting: setting.kind.startswith("table of"))
    for setting in tables_last:
        lines += _account_setting(setting, name, login_url)
    return lines


def _account_setting(setting: SettingDoc, name: str, login_url: str) -> list[str]:
    key = setting.path[-1]
    shown = {
        "login_url": login_url,
        "username": f"env:{secret_variable(name, 'username')}",
        "password": f"env:{secret_variable(name, 'password')}",
    }
    optional = {
        "label": "Our family",
        "portal_url": "https://portal.example.test",
        "institution_key": "your-school-key",
        "role_id": "5afe0000-0000-4000-8000-000000000501",
    }
    lines = _comment(setting.explanation)
    if key in shown:
        lines.append(f"{key} = {format_value(shown[key])}")
    elif key in optional:
        lines.append(f"# {key} = {format_value(optional[key])}")
    elif key == "slugs":
        lines += [f"# [accounts.{name}.slugs]", f"# lucia = {format_value(EXAMPLE_STUDENT_ID)}"]
    else:
        raise KeyError(f"the starter file has no example for accounts.{NAME_PLACEHOLDER}.{key}")
    lines.append("")
    return lines
