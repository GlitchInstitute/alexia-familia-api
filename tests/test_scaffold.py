"""The starter file loads, shows every setting once, and keeps secrets out of the file."""

import dataclasses
import errno
import os
import re
import stat
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

import pytest

from alexia_api.config import ENV_PREFIX, FixedSettings, load_settings, unknown_variables
from alexia_api.doctor import diagnose
from alexia_api.reference import SettingDoc, catalog
from alexia_api.scaffold import (
    ACCOUNT_PATH,
    EXAMPLE_LOGIN_URL,
    ScaffoldError,
    SecretPart,
    next_steps,
    render_starter,
    secret_variable,
    write_starter,
)
from alexia_api.services.keys import FILE_NAME, ApiKeyStore

SETTING_LINE = re.compile(r"^# ([a-z_]+ = .+)$", re.MULTILINE)
TABLE_LINE = re.compile(r"^# (\[[a-z_.]+\])$", re.MULTILINE)
EXAMPLE_FILE = Path(__file__).resolve().parents[1] / "alexia-api.example.toml"
WITHOUT_THE_ACCOUNT = "\n[accounts."


def everything_uncommented(text: str) -> str:
    """The text with the # removed from every setting line and every table line."""
    return TABLE_LINE.sub(r"\1", SETTING_LINE.sub(r"\1", text))


def above_the_account(text: str) -> str:
    return text.partition(WITHOUT_THE_ACCOUNT)[0]


def test_the_active_lines_describe_one_account_and_nothing_else() -> None:
    assert tomllib.loads(render_starter()) == {
        "accounts": {
            "family": {
                "login_url": EXAMPLE_LOGIN_URL,
                "username": "env:PORTAL_FAMILY_USERNAME",
                "password": "env:PORTAL_FAMILY_PASSWORD",
            }
        }
    }


def test_the_starter_loads_as_settings_that_hold_every_default(tmp_path: Path) -> None:
    path = tmp_path / "alexia-api.toml"
    write_starter(path, render_starter("marta"))

    settings = load_settings(path)

    skipped = {"accounts", "state_dir"}
    assert list(settings.accounts) == ["marta"]
    assert settings.state_dir == tmp_path / "state"
    assert settings.model_dump(exclude=skipped) == FixedSettings().model_dump(exclude=skipped)


def test_removing_the_hash_from_every_setting_above_the_account_changes_nothing() -> None:
    active = everything_uncommented(above_the_account(render_starter()))

    assert FixedSettings(**tomllib.loads(active)) == FixedSettings()


def test_every_setting_is_shown_once_in_the_starter() -> None:
    text = render_starter("family")

    for section in catalog():
        for setting in section.settings:
            name = setting.path[-1]
            if setting.kind.startswith("table of"):
                assert text.count(f"# [accounts.family.{name}]") == 1, setting.key
            else:
                assert len(re.findall(rf"^(?:# )?{name} = ", text, re.MULTILINE)) == 1, setting.key


def test_the_comments_say_what_the_model_says_including_the_limits() -> None:
    text = render_starter()
    comments = [line.removeprefix("#").strip() for line in text.splitlines() if line[:1] == "#"]
    said = " ".join(" ".join(comments).split())

    for section in catalog():
        for setting in section.settings:
            assert " ".join(setting.explanation.split()) in said, setting.key
    assert "It must be at least 0.1 and at most 60." in said


def test_a_login_address_that_is_given_replaces_the_example() -> None:
    address = "https://colegio.example.net/ACWeb/LogOn.aspx?key=abc123"

    parsed = tomllib.loads(render_starter("marta", f"  {address}\n"))

    assert parsed["accounts"]["marta"]["login_url"] == address


@pytest.mark.parametrize(
    ("address", "problem"),
    [
        ("http://colegio.example.net/ACWeb/LogOn.aspx?key=abc", "must start with https://"),
        ("https://colegio.example.net/ACWeb/LogOn.aspx", "has no key= in it"),
        ("https://who:pw@colegio.example.net/ACWeb/LogOn.aspx?key=abc", "remove it"),
        ("not an address", "must be a web address"),
        ("", "must be a web address"),
    ],
)
def test_a_login_address_that_would_not_work_is_refused_with_the_reason(
    address: str, problem: str
) -> None:
    with pytest.raises(ScaffoldError) as raised:
        render_starter("marta", address)

    message = str(raised.value)
    assert problem in message
    assert message.startswith("login_url ")


@pytest.mark.parametrize(
    "name", ["", "Marta", "marta_diaz", "marta diaz", "-marta", "marta-", "marta--diaz", "x" * 41]
)
def test_an_account_name_that_cannot_go_in_a_url_is_refused(name: str) -> None:
    with pytest.raises(ScaffoldError, match="not a valid account name"):
        render_starter(name)


def test_a_second_word_in_an_account_name_joins_with_a_hyphen() -> None:
    parsed = tomllib.loads(render_starter("marta-diaz"))

    assert parsed["accounts"]["marta-diaz"]["username"] == "env:PORTAL_MARTA_DIAZ_USERNAME"


@pytest.mark.parametrize(
    ("account", "part", "expected"),
    [
        ("marta", "username", "PORTAL_MARTA_USERNAME"),
        ("marta", "password", "PORTAL_MARTA_PASSWORD"),
        ("marta-diaz", "password", "PORTAL_MARTA_DIAZ_PASSWORD"),
    ],
)
def test_a_secret_variable_is_named_after_its_account(
    account: str, part: SecretPart, expected: str
) -> None:
    assert secret_variable(account, part) == expected


@pytest.mark.parametrize("account", ["api", "alexia-api", "a"])
@pytest.mark.parametrize("part", ["username", "password"])
def test_a_secret_variable_is_never_one_the_server_checks_for_typos(
    account: str, part: SecretPart
) -> None:
    name = secret_variable(account, part)

    assert not name.startswith(ENV_PREFIX)
    assert unknown_variables({name: "value"}) == []


def test_a_new_account_setting_without_an_example_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extra = SettingDoc(
        path=(*ACCOUNT_PATH, "nickname"), kind="text", description="A pet name.", required=False
    )
    sections = tuple(
        dataclasses.replace(section, settings=(*section.settings, extra))
        if section.path == ACCOUNT_PATH
        else section
        for section in catalog()
    )
    monkeypatch.setattr("alexia_api.scaffold.catalog", lambda: sections)

    with pytest.raises(KeyError, match=re.escape("no example for accounts.<name>.nickname")):
        render_starter()


def test_a_table_comes_after_the_plain_settings_whatever_the_model_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sections = tuple(
        dataclasses.replace(section, settings=tuple(reversed(section.settings)))
        if section.path == ACCOUNT_PATH
        else section
        for section in catalog()
    )
    monkeypatch.setattr("alexia_api.scaffold.catalog", lambda: sections)

    text = render_starter("marta")

    assert text.index("# [accounts.marta.slugs]") > text.index("# role_id = ")
    assert text.index("# [accounts.marta.slugs]") > text.index('password = "env:')


def test_the_file_is_written_for_its_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "alexia-api.toml"

    write_starter(path, "x = 1\n")

    assert path.read_text(encoding="utf-8") == "x = 1\n"
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_an_existing_file_is_kept_unless_the_person_asks_to_replace_it(tmp_path: Path) -> None:
    path = tmp_path / "alexia-api.toml"
    path.write_text("mine\n", encoding="utf-8")

    with pytest.raises(ScaffoldError, match="already exists, add --force to replace it"):
        write_starter(path, "new\n")
    assert path.read_text(encoding="utf-8") == "mine\n"

    write_starter(path, "new\n", replace=True)
    assert path.read_text(encoding="utf-8") == "new\n"


def test_folders_that_are_missing_are_made(tmp_path: Path) -> None:
    path = tmp_path / "one" / "two" / "alexia-api.toml"

    write_starter(path, "x = 1\n")

    assert path.read_text(encoding="utf-8") == "x = 1\n"


def test_a_folder_that_cannot_be_made_is_reported(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder", encoding="utf-8")

    with pytest.raises(ScaffoldError, match="cannot be made"):
        write_starter(blocker / "alexia-api.toml", "x = 1\n")


def test_a_place_that_cannot_be_written_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ScaffoldError, match="cannot be written"):
        write_starter(tmp_path, "x = 1\n", replace=True)


def refusing(error: OSError) -> Callable[..., NoReturn]:
    def refuse(*args: object, **kwargs: object) -> NoReturn:
        raise error

    return refuse


def test_the_reason_a_folder_cannot_be_made_is_in_the_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "one" / "alexia-api.toml"
    monkeypatch.setattr(Path, "mkdir", refusing(PermissionError(errno.EACCES, "Permission denied")))

    with pytest.raises(ScaffoldError) as raised:
        write_starter(path, "x = 1\n")

    assert str(raised.value) == f"{path.parent} cannot be made, Permission denied"


def test_the_reason_a_file_cannot_be_written_is_in_the_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "alexia-api.toml"
    monkeypatch.setattr(os, "open", refusing(OSError(errno.EROFS, "Read-only file system")))

    with pytest.raises(ScaffoldError) as raised:
        write_starter(path, "x = 1\n")

    assert str(raised.value) == f"{path} cannot be written, Read-only file system"


def test_an_error_that_gives_no_reason_is_named_by_its_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "alexia-api.toml"
    monkeypatch.setattr(os, "open", refusing(OSError("odd")))

    with pytest.raises(ScaffoldError) as raised:
        write_starter(path, "x = 1\n")

    assert str(raised.value) == f"{path} cannot be written, OSError"


def test_the_steps_start_with_the_address_when_none_was_given() -> None:
    steps = next_steps(Path("alexia-api.toml"), "marta", has_login_url=False)

    assert steps == (
        "Wrote alexia-api.toml with the account marta.\n"
        "\n"
        "Next\n"
        "  1. Open the file and paste the address of your school's login page into login_url.\n"
        "  2. Put your portal login in the environment, so that no secret is in the file.\n"
        "       export PORTAL_MARTA_USERNAME='your user name'\n"
        "       export PORTAL_MARTA_PASSWORD='your password'\n"
        "  3. Make a key for your phone or your program. It is shown once, so copy it.\n"
        "       alexia-api keys create phone\n"
        "  4. Check the setup.\n"
        "       alexia-api doctor\n"
        "  5. Start the server.\n"
        "       alexia-api serve"
    )


def test_the_steps_skip_the_address_when_one_was_given() -> None:
    steps = next_steps(Path("alexia-api.toml"), "marta", has_login_url=True)

    assert "login_url" not in steps
    assert "  1. Put your portal login in the environment" in steps
    assert "  4. Start the server." in steps


def test_the_steps_set_variables_the_way_powershell_does_on_windows() -> None:
    steps = next_steps(Path("alexia-api.toml"), "marta", has_login_url=True, windows=True)

    assert "$env:PORTAL_MARTA_USERNAME = 'your user name'" in steps
    assert "export" not in steps


def test_the_steps_name_the_file_when_it_is_not_the_default_one() -> None:
    steps = next_steps(Path("my conf/family.toml"), "marta", has_login_url=True)

    assert "alexia-api doctor --config 'my conf/family.toml'" in steps
    assert "alexia-api keys create phone --config 'my conf/family.toml'" in steps
    assert "alexia-api serve --config 'my conf/family.toml'" in steps


def test_the_example_file_in_the_repository_is_the_current_starter() -> None:
    assert EXAMPLE_FILE.read_text(encoding="utf-8") == render_starter(), (
        "regenerate it with `pixi run init --print > alexia-api.example.toml`"
    )


def test_the_doctor_finds_only_the_example_address_in_a_fresh_starter(tmp_path: Path) -> None:
    path = tmp_path / "alexia-api.toml"
    write_starter(path, render_starter("marta"))
    ApiKeyStore(tmp_path / "state" / FILE_NAME).create("phone", scopes=["read"], accounts=["*"])
    environ = {"PORTAL_MARTA_USERNAME": "user", "PORTAL_MARTA_PASSWORD": "password"}

    diagnosis = diagnose(path, environ)

    problems = [finding for finding in diagnosis.findings if finding.level != "ok"]
    assert [(finding.level, finding.subject) for finding in problems] == [
        ("fail", "accounts.marta")
    ]
    assert "still the example" in problems[0].message
    assert not diagnosis.blocked
