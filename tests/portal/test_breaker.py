import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from alexia_api.clock import ManualClock
from alexia_api.domain.accounts import Blocked
from alexia_api.domain.ids import InvalidIdError, parse_account_id
from alexia_api.portal.breaker import BreakerStore

ACCOUNT = parse_account_id("family-a")
BLOCKED = Blocked(
    cause="action_required_in_portal",
    since=datetime(2026, 3, 5, 9, 0, tzinfo=UTC),
    interstitial="TxtLegales",
)


def test_a_missing_file_means_no_block(tmp_path: Path) -> None:
    assert BreakerStore(tmp_path).read(ACCOUNT) is None


def test_a_written_block_reads_back_exactly(tmp_path: Path) -> None:
    store = BreakerStore(tmp_path / "breaker")

    store.write(ACCOUNT, BLOCKED)

    assert store.read(ACCOUNT) == BLOCKED
    assert BreakerStore(tmp_path / "breaker").read(ACCOUNT) == BLOCKED


def test_clearing_removes_the_block_and_clearing_twice_is_fine(tmp_path: Path) -> None:
    store = BreakerStore(tmp_path)
    store.write(ACCOUNT, BLOCKED)

    store.clear(ACCOUNT)
    store.clear(ACCOUNT)

    assert store.read(ACCOUNT) is None


def test_the_file_holds_the_cause_and_the_time_and_nothing_secret(tmp_path: Path) -> None:
    store = BreakerStore(tmp_path)

    store.write(ACCOUNT, BLOCKED)

    text = (tmp_path / "family-a.json").read_text(encoding="utf-8")
    assert "action_required_in_portal" in text
    assert "password" not in text


def test_writing_leaves_no_temporary_files_behind(tmp_path: Path) -> None:
    store = BreakerStore(tmp_path)

    store.write(ACCOUNT, BLOCKED)
    store.write(ACCOUNT, BLOCKED)

    assert [path.name for path in tmp_path.iterdir()] == ["family-a.json"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_the_directory_and_file_are_private_to_the_owner(tmp_path: Path) -> None:
    store = BreakerStore(tmp_path / "state")

    store.write(ACCOUNT, BLOCKED)

    assert (tmp_path / "state").stat().st_mode & 0o077 == 0
    assert (tmp_path / "state" / "family-a.json").stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("content", ["", "not json", '{"state": "blocked"}', '{"cause": "x"}'])
def test_a_file_that_cannot_be_read_counts_as_a_block(tmp_path: Path, content: str) -> None:
    clock = ManualClock(datetime(2026, 4, 1, tzinfo=UTC))
    (tmp_path / "family-a.json").write_text(content, encoding="utf-8")

    blocked = BreakerStore(tmp_path, clock).read(ACCOUNT)

    assert blocked == Blocked(cause="state_unreadable", since=datetime(2026, 4, 1, tzinfo=UTC))


def test_a_directory_in_place_of_the_file_counts_as_a_block(tmp_path: Path) -> None:
    (tmp_path / "family-a.json").mkdir()

    blocked = BreakerStore(tmp_path).read(ACCOUNT)

    assert blocked is not None
    assert blocked.cause == "state_unreadable"


def test_an_unreadable_file_can_be_cleared_like_any_other_block(tmp_path: Path) -> None:
    (tmp_path / "family-a.json").write_text("garbage", encoding="utf-8")
    store = BreakerStore(tmp_path)

    store.clear(ACCOUNT)

    assert store.read(ACCOUNT) is None


def test_an_account_name_cannot_escape_the_directory(tmp_path: Path) -> None:
    store = BreakerStore(tmp_path)

    for name in ["../outside", "a/b", "A", ""]:
        with pytest.raises(InvalidIdError):
            store.read(name)  # type: ignore[arg-type]
