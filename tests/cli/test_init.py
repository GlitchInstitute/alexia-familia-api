"""`alexia-api init` writes a starter file, keeps an existing one, and shows the way on."""

import re
import shlex
import sys
from pathlib import Path

import pytest

from alexia_api.config import CONFIG_ENV
from alexia_api.scaffold import render_starter
from alexia_api.services.keys import FILE_NAME, ApiKeyStore
from tests.cli.support import run

LOGIN_URL = "http://localhost:8081/ACWeb/LogOn.aspx?key=demo-school"
EXPORT_LINE = re.compile(r"^\s+export (\w+)='([^']*)'$", re.MULTILINE)


def test_it_writes_the_starter_file_and_lists_the_next_steps(workdir: Path) -> None:
    result = run("init")

    assert result.exit_code == 0
    assert (workdir / "alexia-api.toml").read_text(encoding="utf-8") == render_starter()
    assert result.stdout.startswith("Wrote alexia-api.toml with the account family.\n")
    assert "paste the address of your school's login page" in result.stdout
    assert result.stderr == ""


def test_the_account_and_the_address_go_into_the_file(workdir: Path) -> None:
    result = run("init", "--account", "marta", "--login-url", LOGIN_URL)

    assert result.exit_code == 0
    written = (workdir / "alexia-api.toml").read_text(encoding="utf-8")
    assert written == render_starter("marta", LOGIN_URL)
    assert "with the account marta." in result.stdout
    assert "PORTAL_MARTA_USERNAME" in result.stdout
    assert "login_url" not in result.stdout


def test_a_second_run_leaves_the_first_file_alone(workdir: Path) -> None:
    existing = workdir / "alexia-api.toml"
    existing.write_text("# my edits\n", encoding="utf-8")

    result = run("init")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "Error: alexia-api.toml already exists, add --force to replace it\n"
    assert existing.read_text(encoding="utf-8") == "# my edits\n"


def test_force_replaces_the_file(workdir: Path) -> None:
    existing = workdir / "alexia-api.toml"
    existing.write_text("# my edits\n", encoding="utf-8")

    result = run("init", "--force")

    assert result.exit_code == 0
    assert existing.read_text(encoding="utf-8") == render_starter()


def test_a_named_file_gets_its_folders_and_the_steps_name_it(workdir: Path) -> None:
    result = run("init", "--config", "conf/deep/family.toml")

    assert result.exit_code == 0
    assert (workdir / "conf" / "deep" / "family.toml").is_file()
    named = shlex.quote(str(Path("conf/deep/family.toml")))
    assert f"alexia-api doctor --config {named}" in result.stdout
    assert f"alexia-api keys create phone --config {named}" in result.stdout
    assert f"alexia-api serve --config {named}" in result.stdout


def test_the_environment_names_the_file_when_the_option_is_missing(workdir: Path) -> None:
    named = workdir / "volume" / "alexia-api.toml"

    result = run("init", env={CONFIG_ENV: str(named)})

    assert result.exit_code == 0
    assert named.is_file()
    assert not (workdir / "alexia-api.toml").exists()
    assert f"alexia-api serve --config {shlex.quote(str(named))}" in result.stdout


def test_a_home_folder_in_the_variable_means_the_same_to_init_and_to_the_doctor(
    workdir: Path,
) -> None:
    home = workdir / "home"
    home.mkdir()
    environment = {CONFIG_ENV: "~/alexia-api.toml", "HOME": str(home), "USERPROFILE": str(home)}

    written = run("init", env=environment)
    read = run("doctor", env=environment)

    assert written.exit_code == 0
    assert (home / "alexia-api.toml").is_file()
    assert f"read {home / 'alexia-api.toml'}" in read.stdout


def test_the_short_option_names_the_file_too(workdir: Path) -> None:
    result = run("init", "-c", "short.toml")

    assert result.exit_code == 0
    assert (workdir / "short.toml").is_file()


def test_the_option_wins_over_the_environment(workdir: Path) -> None:
    result = run(
        "init",
        "--config",
        "from-option.toml",
        env={CONFIG_ENV: str(workdir / "from-environment.toml")},
    )

    assert result.exit_code == 0
    assert (workdir / "from-option.toml").is_file()
    assert not (workdir / "from-environment.toml").exists()


def test_print_shows_the_file_and_writes_nothing(workdir: Path) -> None:
    result = run("init", "--print", "--account", "marta", "--login-url", LOGIN_URL)

    assert result.exit_code == 0
    assert result.stdout == render_starter("marta", LOGIN_URL)
    assert result.stderr == ""
    assert list(workdir.iterdir()) == []


def test_print_does_not_mind_a_file_that_exists(workdir: Path) -> None:
    existing = workdir / "alexia-api.toml"
    existing.write_text("# mine\n", encoding="utf-8")

    result = run("init", "--print")

    assert result.exit_code == 0
    assert result.stdout == render_starter()
    assert existing.read_text(encoding="utf-8") == "# mine\n"


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (("--account", "Marta Lopez"), "Error: 'Marta Lopez' is not a valid account name"),
        (("--login-url", "ftp://portal.example.test/?key=x"), "Error: login_url "),
    ],
)
def test_a_bad_value_is_refused_before_anything_is_made(
    workdir: Path, arguments: tuple[str, ...], message: str
) -> None:
    result = run("init", "--config", "new/folder/alexia-api.toml", *arguments)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.startswith(message)
    assert list(workdir.iterdir()) == []


@pytest.mark.parametrize(
    ("platform", "line"),
    [
        ("linux", "export PORTAL_FAMILY_USERNAME='your user name'"),
        ("darwin", "export PORTAL_FAMILY_USERNAME='your user name'"),
        ("win32", "$env:PORTAL_FAMILY_USERNAME = 'your user name'"),
    ],
)
def test_the_steps_use_the_shell_of_the_platform(
    monkeypatch: pytest.MonkeyPatch, platform: str, line: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)

    result = run("init")

    assert result.exit_code == 0
    assert line in result.stdout


def test_the_commands_it_prints_make_the_doctor_pass(
    workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    printed = run("init", "--account", "marta", "--login-url", LOGIN_URL)
    environment = dict(EXPORT_LINE.findall(printed.stdout))
    ApiKeyStore(workdir / "state" / FILE_NAME).create("phone", scopes=["read"], accounts=["*"])

    result = run("doctor", env=environment)

    assert environment.keys() == {"PORTAL_MARTA_USERNAME", "PORTAL_MARTA_PASSWORD"}
    assert result.exit_code == 0
    assert result.stdout.rstrip().endswith("Everything checks out.")
