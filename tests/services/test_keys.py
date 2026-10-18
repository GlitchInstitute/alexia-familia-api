"""API keys are shown once, stored only as hashes, and checked against every stored hash."""

import hashlib
import hmac
import logging
import os
import stat
import sys
from pathlib import Path

import pytest

from alexia_api.clock import ManualClock
from alexia_api.domain.security import Principal
from alexia_api.services.keys import ApiKeyStore, KeyStoreError


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "state" / "api-keys.json"


@pytest.fixture
def store(path: Path, clock: ManualClock) -> ApiKeyStore:
    return ApiKeyStore(path, clock)


def test_a_new_key_is_shown_once_and_works(store: ApiKeyStore) -> None:
    issued = store.create("home-assistant", scopes={"read"}, accounts={"marta"})

    assert issued.key.startswith("afk_")
    assert store.authenticate(issued.key) == Principal(
        key_name="home-assistant", scopes=frozenset({"read"}), accounts=frozenset({"marta"})
    )


def test_two_keys_are_never_the_same(store: ApiKeyStore) -> None:
    first = store.create("one", scopes={"read"}, accounts={"*"})
    second = store.create("two", scopes={"read"}, accounts={"*"})

    assert first.key != second.key


def test_the_file_holds_a_hash_and_never_the_key(store: ApiKeyStore, path: Path) -> None:
    issued = store.create("home-assistant", scopes={"read"}, accounts={"marta"})

    text = path.read_text(encoding="utf-8")

    assert issued.key not in text
    assert hashlib.sha256(issued.key.encode()).hexdigest() in text
    assert issued.record.sha256 in text


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no Unix file modes")
def test_the_file_and_its_folder_are_private(store: ApiKeyStore, path: Path) -> None:
    store.create("home-assistant", scopes={"read"}, accounts={"marta"})

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_a_creation_time_comes_from_the_clock(store: ApiKeyStore, clock: ManualClock) -> None:
    issued = store.create("home-assistant", scopes={"read"}, accounts={"marta"})

    assert issued.record.created_at == clock.now()


@pytest.mark.parametrize("presented", ["", "afk_", "afk_not-a-real-key", "Bearer afk_x", " "])
def test_a_wrong_key_is_refused(store: ApiKeyStore, presented: str) -> None:
    store.create("home-assistant", scopes={"read"}, accounts={"marta"})

    assert store.authenticate(presented) is None


def test_a_key_that_is_one_character_off_is_refused(store: ApiKeyStore) -> None:
    issued = store.create("home-assistant", scopes={"read"}, accounts={"marta"})
    last = "A" if issued.key[-1] != "A" else "B"

    assert store.authenticate(issued.key[:-1] + last) is None


def test_every_stored_hash_is_compared_so_the_position_of_a_key_does_not_show(
    store: ApiKeyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = store.create("one", scopes={"read"}, accounts={"*"})
    store.create("two", scopes={"read"}, accounts={"*"})
    store.create("three", scopes={"read"}, accounts={"*"})
    compared: list[int] = []
    real = hmac.compare_digest

    def spy(left: str, right: str) -> bool:
        compared.append(1)
        return real(left, right)

    monkeypatch.setattr(hmac, "compare_digest", spy)

    assert store.authenticate(first.key) is not None
    assert len(compared) == 3


def test_a_name_can_be_used_once(store: ApiKeyStore) -> None:
    store.create("home-assistant", scopes={"read"}, accounts={"*"})

    with pytest.raises(KeyStoreError, match="already exists"):
        store.create("home-assistant", scopes={"write"}, accounts={"*"})


@pytest.mark.parametrize("name", ["", "Home Assistant", "home_assistant", "-x", "x" * 41])
def test_a_name_must_be_a_short_slug(store: ApiKeyStore, name: str) -> None:
    with pytest.raises(KeyStoreError, match="name"):
        store.create(name, scopes={"read"}, accounts={"*"})


def test_a_key_needs_at_least_one_scope_and_one_account(store: ApiKeyStore) -> None:
    with pytest.raises(KeyStoreError, match="scope"):
        store.create("one", scopes=set(), accounts={"*"})
    with pytest.raises(KeyStoreError, match="account"):
        store.create("one", scopes={"read"}, accounts=set())


def test_an_account_must_be_a_valid_name_or_star(store: ApiKeyStore) -> None:
    with pytest.raises(KeyStoreError, match="Marta Family"):
        store.create("one", scopes={"read"}, accounts={"Marta Family"})


def test_star_stands_for_all_accounts_and_absorbs_the_rest(store: ApiKeyStore) -> None:
    issued = store.create("one", scopes={"read"}, accounts={"marta", "*"})

    assert issued.record.accounts == ["*"]


def test_an_account_named_twice_is_kept_once(store: ApiKeyStore) -> None:
    issued = store.create("one", scopes={"read"}, accounts=["pablo", "marta", "pablo"])

    assert issued.record.accounts == ["marta", "pablo"]


def test_keys_are_listed_without_their_secrets(store: ApiKeyStore) -> None:
    store.create("one", scopes={"read", "feed"}, accounts={"marta"})
    store.create("two", scopes={"admin"}, accounts={"*"})

    listed = store.records()

    assert [record.name for record in listed] == ["one", "two"]
    assert listed[0].scopes == ["feed", "read"]


def test_a_key_can_be_revoked(store: ApiKeyStore) -> None:
    issued = store.create("one", scopes={"read"}, accounts={"*"})
    other = store.create("two", scopes={"read"}, accounts={"*"})

    assert store.revoke("one") is True

    assert store.authenticate(issued.key) is None
    assert store.authenticate(other.key) is not None
    assert store.revoke("one") is False


def test_a_running_server_sees_keys_that_another_process_adds_or_revokes(
    path: Path, clock: ManualClock
) -> None:
    server = ApiKeyStore(path, clock)
    command_line = ApiKeyStore(path, clock)
    assert server.authenticate("afk_anything") is None

    issued = command_line.create("one", scopes={"read"}, accounts={"*"})
    assert server.authenticate(issued.key) is not None

    command_line.revoke("one")
    assert server.authenticate(issued.key) is None


def test_with_no_file_there_are_no_keys(store: ApiKeyStore) -> None:
    assert store.records() == ()
    assert store.authenticate("afk_anything") is None


def test_a_file_that_cannot_be_read_refuses_everyone_and_says_so_once(
    store: ApiKeyStore, path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    issued = store.create("one", scopes={"read"}, accounts={"*"})
    path.write_text("{ this is not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert store.authenticate(issued.key) is None
        assert store.authenticate(issued.key) is None

    assert len([line for line in caplog.records if "api-keys.json" in line.getMessage()]) == 1
    assert "this is not json" not in caplog.text


def test_a_file_that_cannot_be_read_is_never_overwritten(store: ApiKeyStore, path: Path) -> None:
    store.create("one", scopes={"read"}, accounts={"*"})
    path.write_text("{ this is not json", encoding="utf-8")

    with pytest.raises(KeyStoreError, match="cannot be read"):
        store.create("two", scopes={"read"}, accounts={"*"})

    assert path.read_text(encoding="utf-8") == "{ this is not json"


def test_a_failed_write_leaves_no_half_written_file(
    store: ApiKeyStore, path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.create("one", scopes={"read"}, accounts={"*"})
    before = path.read_text(encoding="utf-8")

    def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)

    with pytest.raises(OSError, match="disk full"):
        store.create("two", scopes={"read"}, accounts={"*"})

    assert path.read_text(encoding="utf-8") == before
    assert sorted(entry.name for entry in path.parent.iterdir()) == ["api-keys.json"]
