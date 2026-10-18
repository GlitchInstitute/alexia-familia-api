"""The privacy check refuses real-looking data and never repeats it."""

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_privacy.py"
SYNTHETIC_GUID = "5afe0000-0000-4000-8000-0000000000a1"
# Built from pieces, so the scanner finds nothing in this very file.
REAL_LOOKING_GUID = "-".join(["3f2b8c1e", "9a4d", "4e7b", "8c55", "0d1e2f3a4b5c"])
PRIVATE_ADDRESS = "someone.private" + "@" + "gmail.com"
OTHER_ADDRESS = "x" + "@" + "y.org"


def run(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), str(root), *extra],
        capture_output=True,
        text=True,
        check=False,
    )


def write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def digest_of(word: str) -> str:
    return hashlib.sha256(word.encode()).hexdigest()


def test_a_clean_tree_passes(tmp_path: Path) -> None:
    write(tmp_path, "docs/a.md", f"Child {SYNTHETIC_GUID} writes to teacher@example.test\n")

    result = run(tmp_path)

    assert result.returncode == 0
    assert "check_privacy ok files=1 denylist=absent" in result.stdout


def test_a_guid_outside_the_synthetic_range_fails_without_echoing_it(tmp_path: Path) -> None:
    write(tmp_path, "tests/data.py", f"x = 1\nSTUDENT = '{REAL_LOOKING_GUID}'\n")

    result = run(tmp_path)

    assert result.returncode == 1
    assert "tests/data.py:2 GUID outside the synthetic range" in result.stderr
    assert REAL_LOOKING_GUID not in result.stderr + result.stdout


def test_an_email_outside_the_safe_domains_fails_without_echoing_it(tmp_path: Path) -> None:
    write(tmp_path, "README.md", f"Write to {PRIVATE_ADDRESS} please\n")

    result = run(tmp_path)

    assert result.returncode == 1
    assert "README.md:1 email outside the safe domains" in result.stderr
    assert "someone.private" not in result.stderr + result.stdout


@pytest.mark.parametrize("address", ["a@example.test", "1+x@users.noreply.github.com"])
def test_safe_email_domains_pass(tmp_path: Path, address: str) -> None:
    write(tmp_path, "a.md", f"{address}\n")

    assert run(tmp_path).returncode == 0


def test_a_word_from_the_denylist_fails_and_accents_do_not_hide_it(tmp_path: Path) -> None:
    write(tmp_path, ".denylist.sha256", f"{digest_of('zorgblat')}\n")
    write(tmp_path, "notes.md", "A child called Zörgblat goes to school\n")
    write(tmp_path, "fine.md", "Nothing to see\n")

    result = run(tmp_path)

    assert result.returncode == 1
    assert "notes.md:1 word from the local denylist" in result.stderr
    assert "fine.md" not in result.stderr
    assert "orgblat" not in result.stderr + result.stdout


def test_the_denylist_can_be_named_on_the_command_line(tmp_path: Path) -> None:
    list_file = tmp_path / "elsewhere.txt"
    list_file.write_text(f"{digest_of('quuxling')}\n", encoding="utf-8")
    scanned = tmp_path / "tree"
    write(scanned, "a.md", "quuxling\n")

    result = run(scanned, "--denylist", str(list_file))

    assert result.returncode == 1
    assert "a.md:1 word from the local denylist" in result.stderr


def test_short_words_are_not_tokens(tmp_path: Path) -> None:
    write(tmp_path, ".denylist.sha256", f"{digest_of('ana')}\n")
    write(tmp_path, "a.md", "ana ana ana\n")

    assert run(tmp_path).returncode == 0


def test_lock_files_caches_and_binary_files_are_skipped(tmp_path: Path) -> None:
    write(tmp_path, "pixi.lock", f"{REAL_LOOKING_GUID}\n")
    write(tmp_path, ".pixi/envs/x.txt", f"{REAL_LOOKING_GUID}\n")
    write(tmp_path, "__pycache__/x.txt", f"{REAL_LOOKING_GUID}\n")
    (tmp_path / "image.bin").write_bytes(bytes(range(256)) * 4)
    write(tmp_path, "ok.md", "fine\n")

    result = run(tmp_path)

    assert result.returncode == 0
    assert "files=1 " in result.stdout


def test_it_uses_git_to_skip_ignored_files(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
    write(tmp_path, ".gitignore", "secret/\n")
    write(tmp_path, "secret/a.md", f"{REAL_LOOKING_GUID}\n")
    write(tmp_path, "public/b.md", "fine\n")

    result = run(tmp_path)

    assert result.returncode == 0


def commit_all(root: Path, message: str) -> None:
    identity = ["-c", "user.name=Test", "-c", "user.email=test@example.test"]
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)  # noqa: S603, S607
    subprocess.run(  # noqa: S603
        ["git", "-C", str(root), *identity, "commit", "-q", "-m", message],  # noqa: S607
        check=True,
    )


def test_a_leak_that_was_deleted_later_is_still_found_in_history(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
    write(tmp_path, "a.md", "fine\nstill fine\n")
    commit_all(tmp_path, "clean")
    write(tmp_path, "a.md", f"fine\nstill fine\nchild {REAL_LOOKING_GUID}\n")
    commit_all(tmp_path, "oops")
    write(tmp_path, "a.md", "fine\nstill fine\n")
    commit_all(tmp_path, "remove")

    working_tree = run(tmp_path)
    history = run(tmp_path, "--history")

    assert working_tree.returncode == 0
    assert history.returncode == 1
    assert ":a.md:3 GUID outside the synthetic range" in history.stderr
    assert "in 1 file(s) and 3 commit(s)" in history.stderr
    assert REAL_LOOKING_GUID not in history.stderr + history.stdout


def test_a_clean_history_passes(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
    write(tmp_path, "a.md", f"child {SYNTHETIC_GUID}\n")
    commit_all(tmp_path, "one")
    write(tmp_path, "b.md", "two\n")
    commit_all(tmp_path, "two")

    result = run(tmp_path, "--history")

    assert result.returncode == 0
    assert "check_privacy ok files=2 commits=2 " in result.stdout


def git_in(root: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(root), *arguments], check=True)  # noqa: S603, S607


def test_history_stops_at_the_checked_out_commit(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
    write(tmp_path, "a.md", "fine\n")
    commit_all(tmp_path, "clean")
    write(tmp_path, "a.md", f"fine\nchild {REAL_LOOKING_GUID}\n")
    commit_all(tmp_path, "leak")
    git_in(tmp_path, "checkout", "-q", "HEAD~1")

    result = run(tmp_path, "--history")

    assert result.returncode == 0
    assert "check_privacy ok files=1 commits=1 " in result.stdout


def test_all_refs_looks_at_branches_that_the_checkout_does_not_contain(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
    write(tmp_path, "a.md", "fine\n")
    commit_all(tmp_path, "clean")
    git_in(tmp_path, "checkout", "-q", "-b", "elsewhere")
    write(tmp_path, "b.md", f"child {REAL_LOOKING_GUID}\n")
    commit_all(tmp_path, "leak on another branch")
    git_in(tmp_path, "checkout", "-q", "-")

    here = run(tmp_path, "--history")
    everywhere = run(tmp_path, "--all-refs")

    assert here.returncode == 0
    assert everywhere.returncode == 1
    assert ":b.md:1 GUID outside the synthetic range" in everywhere.stderr
    assert "in 1 file(s) and 2 commit(s)" in everywhere.stderr
    assert REAL_LOOKING_GUID not in everywhere.stderr + everywhere.stdout


def test_history_mode_on_a_repository_without_commits_checks_none(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
    write(tmp_path, "a.md", "fine\n")

    result = run(tmp_path, "--history")

    assert result.returncode == 0
    assert "commits=0" in result.stdout


def test_every_problem_is_counted(tmp_path: Path) -> None:
    write(tmp_path, "a.md", f"{REAL_LOOKING_GUID} and {OTHER_ADDRESS}\n")

    result = run(tmp_path)

    assert result.returncode == 1
    assert "2 problem(s) in 1 file(s)" in result.stderr
