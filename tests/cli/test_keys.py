"""`alexia-api keys` makes, lists, and revokes the keys that the server checks."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from alexia_api.cli.keys import ScopeName
from alexia_api.clock import ManualClock
from alexia_api.config import CONFIG_ENV
from alexia_api.domain.security import SCOPES, Principal
from alexia_api.services.keys import FILE_NAME, ApiKeyStore, hash_key
from tests.cli.support import run
from tests.workspace import write_config

NOT_READABLE = f"Error: {FILE_NAME} cannot be read, fix or remove the file first\n"
SAVED = "Copy it now. It is shown once, and the server keeps only a hash of it."


@pytest.fixture
def keys_file(config: Path) -> Path:
    """Where the commands keep the keys, next to the configuration file."""
    return config.parent / "state" / FILE_NAME


@pytest.fixture
def store(keys_file: Path) -> ApiKeyStore:
    """The key file, read the way the server reads it."""
    return ApiKeyStore(keys_file)


def names(store: ApiKeyStore) -> list[str]:
    return [record.name for record in store.records()]


def test_the_scopes_on_offer_are_the_scopes_the_server_knows() -> None:
    assert [scope.value for scope in ScopeName] == list(SCOPES)


def test_without_a_command_it_lists_the_three_it_has() -> None:
    result = run("keys")

    for command in ("create", "list", "revoke"):
        assert command in result.output


def test_create_shows_the_key_alone_on_standard_output(store: ApiKeyStore) -> None:
    result = run("keys", "create", "phone")

    key = result.stdout.strip()
    assert result.exit_code == 0
    assert result.stdout == f"{key}\n"
    assert store.authenticate(key) == Principal(
        key_name="phone", scopes=frozenset({"read"}), accounts=frozenset({"*"})
    )
    assert result.stderr.splitlines() == [
        "Made the key phone with the scope read, for all accounts.",
        SAVED,
    ]


def test_create_needs_no_portal_login_in_the_environment(store: ApiKeyStore) -> None:
    result = run("keys", "create", "phone", env={"MARTA_USER": None, "MARTA_PASSWORD": None})

    assert result.exit_code == 0
    assert names(store) == ["phone"]


def test_create_takes_each_scope_and_account_once(store: ApiKeyStore) -> None:
    result = run(
        "keys", "create", "tablet", "-s", "write", "-s", "read", "-a", "marta", "-a", "marta"
    )

    [record] = store.records()
    assert result.exit_code == 0
    assert (record.scopes, record.accounts) == (["read", "write"], ["marta"])
    assert result.stderr.splitlines() == [
        "Made the key tablet with the scopes read and write, for the account marta.",
        SAVED,
    ]


def test_create_writes_three_scopes_and_two_accounts_as_a_sentence() -> None:
    result = run(
        *("keys", "create", "boss"),
        *("--scope", "read", "--scope", "write", "--scope", "admin"),
        *("--account", "marta", "--account", "pablo"),
    )

    assert result.stderr.splitlines()[0] == (
        "Made the key boss with the scopes admin, read and write, for the accounts marta and pablo."
    )


def test_create_notes_an_account_that_is_not_configured_and_still_makes_the_key(
    store: ApiKeyStore,
) -> None:
    result = run("keys", "create", "tablet", "--account", "marta", "--account", "marat")

    assert result.exit_code == 0
    assert result.stderr.splitlines() == [
        "Made the key tablet with the scope read, for the accounts marat and marta.",
        "Note: no account named marat is configured yet.",
        SAVED,
    ]
    assert names(store) == ["tablet"]


def test_create_notes_every_missing_account_in_alphabetical_order() -> None:
    unknown = ["delta", "alpha", "echo", "bravo", "charlie", "foxtrot"]

    result = run("keys", "create", "tablet", *[f"--account={name}" for name in unknown])

    notes = [line for line in result.stderr.splitlines() if line.startswith("Note: ")]
    assert notes == [
        f"Note: no account named {name} is configured yet." for name in sorted(unknown)
    ]


def test_create_refuses_a_name_that_is_taken(store: ApiKeyStore) -> None:
    run("keys", "create", "phone")
    before = store.records()

    result = run("keys", "create", "phone")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "Error: a key named phone already exists\n"
    assert store.records() == before


def test_create_refuses_a_name_that_is_not_a_slug(store: ApiKeyStore) -> None:
    result = run("keys", "create", "Phone 2")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        "Error: a key name is 1 to 40 lower case letters, digits, and hyphens\n"
    )
    assert names(store) == []


def test_an_unknown_scope_is_a_usage_error(store: ApiKeyStore) -> None:
    result = run("keys", "create", "phone", "--scope", "bogus")

    assert result.exit_code == 2
    assert "'bogus' is not one of 'read', 'write', 'admin', 'feed'" in result.stderr
    assert names(store) == []


@pytest.mark.parametrize("command", ["create", "revoke"])
def test_a_key_needs_a_name(command: str, store: ApiKeyStore) -> None:
    result = run("keys", command)

    assert result.exit_code == 2
    assert "Missing argument 'NAME'" in result.stderr
    assert names(store) == []


def test_list_says_when_there_are_no_keys_and_writes_nothing(keys_file: Path) -> None:
    result = run("keys", "list")

    assert result.exit_code == 0
    assert result.stdout == "There are no keys. Make one with `alexia-api keys create NAME`.\n"
    assert not keys_file.parent.exists()


def test_list_shows_each_key_in_a_table_and_never_a_secret(keys_file: Path) -> None:
    clock = ManualClock(datetime(2026, 3, 9, 23, 59, tzinfo=UTC))
    made = ApiKeyStore(keys_file, clock)
    phone = made.create("phone", scopes=["read"], accounts=["*"])
    made.create("tablet", scopes=["read", "write"], accounts=["marta", "pablo"])
    made.create("calendar", scopes=["feed"], accounts=["marta"])

    result = run("keys", "list")

    assert result.exit_code == 0
    assert result.stdout == (
        "NAME      SCOPES      ACCOUNTS     CREATED\n"
        "phone     read        *            2026-03-09\n"
        "tablet    read,write  marta,pablo  2026-03-09\n"
        "calendar  feed        marta        2026-03-09\n"
    )
    for secret in (phone.key, hash_key(phone.key), "afk_"):
        assert secret not in result.stdout


def test_revoke_removes_the_key_at_once(store: ApiKeyStore) -> None:
    key = run("keys", "create", "phone").stdout.strip()
    run("keys", "create", "tablet")

    result = run("keys", "revoke", "phone")

    assert result.exit_code == 0
    assert result.stdout == "Revoked the key phone. A running server stops accepting it at once.\n"
    assert store.authenticate(key) is None
    assert names(store) == ["tablet"]


def test_revoke_names_the_keys_there_are_when_the_name_is_wrong(store: ApiKeyStore) -> None:
    run("keys", "create", "phone")
    run("keys", "create", "tablet")

    result = run("keys", "revoke", "phoen")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "Error: no key is named phoen, the keys are phone and tablet\n"
    assert names(store) == ["phone", "tablet"]


def test_revoke_says_so_when_there_are_no_keys_and_writes_nothing(keys_file: Path) -> None:
    result = run("keys", "revoke", "phone")

    assert result.exit_code == 1
    assert result.stderr == "Error: no key is named phone, there are no keys\n"
    assert not keys_file.parent.exists()


def test_a_key_file_that_cannot_be_read_is_never_overwritten(keys_file: Path) -> None:
    keys_file.parent.mkdir()
    keys_file.write_text("not json", encoding="utf-8")

    for arguments in (("create", "phone"), ("list",), ("revoke", "phone")):
        result = run("keys", *arguments)

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr == NOT_READABLE
    assert keys_file.read_text(encoding="utf-8") == "not json"


def test_a_configuration_that_does_not_load_stops_every_command(workdir: Path) -> None:
    write_config(workdir, top="allow_wrties = true")

    for arguments in (("create", "phone"), ("list",), ("revoke", "phone")):
        result = run("keys", *arguments)

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr.startswith("Error: ")
        assert "allow_wrties" in result.stderr


def test_a_variable_that_names_a_missing_file_is_an_error_and_not_a_crash(workdir: Path) -> None:
    result = run("keys", "list", env={CONFIG_ENV: str(workdir / "missing.toml")})

    assert result.exit_code == 1
    assert result.stderr.startswith("Error: ALEXIA_API_CONFIG points to ")
    assert result.stderr.endswith("missing.toml, which does not exist\n")


def test_the_config_option_names_the_file(tmp_path: Path, workdir: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    path = write_config(elsewhere)

    result = run("keys", "create", "phone", "-c", str(path))

    assert result.exit_code == 0
    assert (elsewhere / "state" / FILE_NAME).is_file()
    assert not (workdir / "state").exists()
