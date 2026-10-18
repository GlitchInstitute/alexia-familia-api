"""The accounts commands show which logins are paused and lift a pause when a person asks."""

import re
import shlex
from pathlib import Path
from typing import get_args

import pytest

from alexia_api.domain.errors import BREAKER_CAUSE_TEXT, BreakerCause
from alexia_api.domain.ids import parse_account_id
from alexia_api.portal.breaker import BREAKER_DIRECTORY, BreakerStore
from tests.cli.support import run
from tests.workspace import ENVIRON, HEALTHY_ACCOUNT, block, make_key, write_config

PABLO = HEALTHY_ACCOUNT.replace("marta", "pablo").replace("MARTA", "PABLO").replace("8081", "8082")
PABLO_THEN_MARTA = PABLO + HEALTHY_ACCOUNT
PAUSED_AT = "since 2026-10-18 20:15 +0000"
NEEDING_A_FILE = (("accounts", "list"), ("accounts", "reset", "marta"))
# Linux says a folder is a directory. macOS and Windows say permission is denied.
UNLINK_OF_A_FOLDER = (IsADirectoryError, PermissionError)


def breakers(workdir: Path) -> BreakerStore:
    return BreakerStore(workdir / "state" / BREAKER_DIRECTORY)


def test_the_list_shows_each_account_and_its_portal_in_the_order_of_the_file(
    workdir: Path,
) -> None:
    write_config(workdir, account=PABLO_THEN_MARTA)

    result = run("accounts", "list")

    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.stdout == (
        "ACCOUNT  PORTAL          LOGINS\n"
        "pablo    localhost:8082  allowed\n"
        "marta    localhost:8081  allowed\n"
    )


@pytest.mark.parametrize("cause", get_args(BreakerCause))
def test_a_paused_account_is_listed_with_when_and_why(workdir: Path, cause: BreakerCause) -> None:
    write_config(workdir, account=PABLO_THEN_MARTA)
    block(workdir, cause)

    result = run("accounts", "list")

    _, pablo, marta = result.stdout.splitlines()
    assert result.exit_code == 0
    assert pablo.endswith("allowed")
    assert marta.endswith(f"paused {PAUSED_AT} because {BREAKER_CAUSE_TEXT[cause]}")


def test_the_list_says_in_plain_words_why_a_wrong_password_paused_an_account(
    config: Path, workdir: Path
) -> None:
    block(workdir, "invalid_credentials")

    result = run("accounts", "list")

    assert result.stdout.splitlines()[1] == (
        "marta    localhost:8081  paused since 2026-10-18 20:15 +0000 because the portal "
        "rejected the user name or password"
    )


def test_without_accounts_the_list_says_how_to_add_one() -> None:
    result = run("accounts", "list")

    assert result.exit_code == 0
    assert result.stdout == (
        "There are no accounts. Add one to the configuration file, "
        "or run `alexia-api init` to write a starter file.\n"
    )


def test_the_list_needs_no_secret(config: Path) -> None:
    result = run("accounts", "list", env={"MARTA_USER": None, "MARTA_PASSWORD": None})

    assert result.exit_code == 0


def test_a_reset_lifts_the_pause_and_says_what_happens_next(config: Path, workdir: Path) -> None:
    block(workdir, "invalid_credentials")

    result = run("accounts", "reset", "marta")

    assert result.exit_code == 0
    assert result.stdout == (
        "Lifted the pause on marta. Logins had been paused since 2026-10-18 20:15 +0000 because "
        "the portal rejected the user name or password. The server tries to log in at the next "
        "request that needs the portal. If the cause is not fixed, the pause comes back after "
        "that one try.\n"
    )
    assert breakers(workdir).read(parse_account_id("marta")) is None


def test_a_reset_lifts_only_the_pause_on_the_account_it_names(workdir: Path) -> None:
    write_config(workdir, account=PABLO_THEN_MARTA)
    block(workdir, "invalid_credentials", "marta")
    block(workdir, "refused_login", "pablo")

    run("accounts", "reset", "pablo")

    store = breakers(workdir)
    still_paused = store.read(parse_account_id("marta"))
    assert store.read(parse_account_id("pablo")) is None
    assert still_paused is not None
    assert still_paused.cause == "invalid_credentials"


def test_a_reset_of_an_account_that_is_not_paused_changes_nothing(
    config: Path, workdir: Path
) -> None:
    result = run("accounts", "reset", "marta")

    assert result.exit_code == 0
    assert result.stdout == "Logins to marta are not paused. There is nothing to reset.\n"
    assert not (workdir / "state").exists()


def test_a_reset_names_the_accounts_that_exist_when_the_name_is_wrong(workdir: Path) -> None:
    write_config(workdir, account=PABLO_THEN_MARTA)

    result = run("accounts", "reset", "Marta")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "Error: no account is named Marta, the accounts are pablo and marta\n"


def test_a_reset_says_so_when_no_account_is_configured() -> None:
    result = run("accounts", "reset", "marta")

    assert result.exit_code == 1
    assert result.stderr == "Error: no account is named marta, there are no accounts\n"


def test_a_reset_needs_the_name_of_an_account() -> None:
    result = run("accounts", "reset")

    assert result.exit_code == 2
    assert "Missing argument 'NAME'" in result.stderr


def test_a_pause_that_cannot_be_removed_is_reported_with_the_reason_and_left_alone(
    config: Path, workdir: Path
) -> None:
    stuck = workdir / "state" / BREAKER_DIRECTORY / "marta.json"
    stuck.mkdir(parents=True)
    with pytest.raises(UNLINK_OF_A_FOLDER) as refused:
        stuck.unlink()

    result = run("accounts", "reset", "marta")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        f"Error: the pause on marta cannot be lifted, {refused.value.strerror}\n"
    )
    assert stuck.is_dir()


def test_a_block_file_that_cannot_be_read_counts_as_a_pause_and_a_reset_removes_it(
    config: Path, workdir: Path
) -> None:
    damaged = workdir / "state" / BREAKER_DIRECTORY / "marta.json"
    damaged.parent.mkdir(parents=True)
    damaged.write_text("not json", encoding="utf-8")
    why = "because the saved block file could not be read"

    listed = run("accounts", "list")
    lifted = run("accounts", "reset", "marta")

    assert why in listed.stdout
    assert lifted.exit_code == 0
    assert why in lifted.stdout
    assert not damaged.exists()


@pytest.mark.parametrize(
    ("arguments", "shows"),
    [
        (("accounts", "list"), "marta    localhost:8081  allowed"),
        (("accounts", "reset", "marta"), "Logins to marta are not paused."),
    ],
    ids=["list", "reset"],
)
def test_the_option_names_the_file_when_the_folder_has_none(
    tmp_path: Path, arguments: tuple[str, ...], shows: str
) -> None:
    path = write_config(tmp_path)

    result = run(*arguments, "-c", str(path))

    assert result.exit_code == 0
    assert shows in result.stdout


@pytest.mark.parametrize("arguments", NEEDING_A_FILE, ids=" ".join)
def test_a_file_that_does_not_load_is_an_error_and_not_a_traceback(
    workdir: Path, arguments: tuple[str, ...]
) -> None:
    (workdir / "alexia-api.toml").write_text("this is not toml", encoding="utf-8")

    result = run(*arguments)

    assert result.exit_code == 1
    assert result.stderr.startswith("Error: ")
    assert "Traceback" not in result.output


def test_the_command_the_doctor_gives_for_a_pause_works(workdir: Path) -> None:
    write_config(workdir)
    make_key(workdir)
    block(workdir, "invalid_credentials")

    advice = run("doctor", env=ENVIRON)
    [command] = re.findall(r"`(alexia-api accounts [^`]+)`", advice.stdout)
    fixed = run(*shlex.split(command)[1:])
    after = run("doctor", env=ENVIRON)

    assert advice.exit_code == 1
    assert fixed.exit_code == 0
    assert after.exit_code == 0
    assert "paused" not in after.stdout
