"""The state directory check says whether the server can keep its files, and makes none."""

import os
import sys
from pathlib import Path

import pytest

from alexia_api.services.health import state_dir_writable

cannot_deny_access = sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0)


def test_a_directory_that_exists_and_can_be_written_is_fine(tmp_path: Path) -> None:
    assert state_dir_writable(tmp_path)


def test_a_directory_that_does_not_exist_is_fine_when_its_parent_can_be_written(
    tmp_path: Path,
) -> None:
    wanted = tmp_path / "state"

    assert state_dir_writable(wanted)
    assert not wanted.exists()


def test_several_missing_levels_are_fine_when_the_nearest_parent_can_be_written(
    tmp_path: Path,
) -> None:
    wanted = tmp_path / "a" / "b" / "state"

    assert state_dir_writable(wanted)
    assert not (tmp_path / "a").exists()


def test_a_file_is_not_a_state_directory_even_when_it_can_be_run_and_written(
    tmp_path: Path,
) -> None:
    occupied = tmp_path / "state"
    occupied.write_text("not a directory", encoding="utf-8")
    occupied.chmod(0o700)

    assert not state_dir_writable(occupied)


def test_nothing_is_fine_when_not_even_the_top_of_the_path_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "exists", lambda _self: False)

    assert not state_dir_writable(tmp_path / "state")


def test_a_directory_cannot_be_made_below_a_file(tmp_path: Path) -> None:
    occupied = tmp_path / "state"
    occupied.write_text("not a directory", encoding="utf-8")

    assert not state_dir_writable(occupied / "keys")


def test_a_relative_path_is_judged_from_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert state_dir_writable(Path("state"))


@pytest.mark.skipif(cannot_deny_access, reason="this account can write anywhere")
@pytest.mark.parametrize(
    ("mode", "why"),
    [(0o500, "it can be entered but not written"), (0o600, "it can be written but not entered")],
)
def test_a_directory_that_cannot_be_used_is_not_fine(tmp_path: Path, mode: int, why: str) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(mode)
    try:
        assert not state_dir_writable(locked), why
        assert not state_dir_writable(locked / "state"), why
    finally:
        locked.chmod(0o700)
