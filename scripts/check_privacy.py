#!/usr/bin/env python3
"""Fail when a file holds something that looks like real personal data.

This repository is public and its tests, fixtures, and docs must only hold invented data. The
check has three rules.

1. A GUID outside the synthetic range `5afe0000-0000-4000-8000-xxxxxxxxxxxx`.
2. An email address outside the safe domains. These are the names that RFC 2606 and RFC 6761
   reserve for examples and tests, and the GitHub no-reply domain, so no real person owns an
   address there.
3. A word whose hash is in a local denylist. The denylist is opt-in and never committed. It is a
   file with one SHA-256 digest per line, made from lower-cased, accent-stripped words of at
   least four letters, so the file itself does not reveal the names it protects.

The report names the file, the line, and the rule. It never prints the text that matched, so a
CI log cannot leak what the check found. With `--history` it also checks every line that any
commit in the checked-out history ever added, because a leak that was deleted later is still
public. The answer depends only on the commit that is checked out, so `git bisect` can use it.
With `--all-refs` it checks every branch, tag, and remote branch instead. Run that before you
publish.
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
import unicodedata
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final

GUID: Final = re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.IGNORECASE)
SYNTHETIC_GUID: Final = re.compile(r"5afe0000-0000-4000-8000-[0-9a-f]{12}", re.IGNORECASE)
EMAIL: Final = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
HUNK: Final = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
RESERVED_TOP_LEVEL_NAMES: Final = frozenset({"test", "example", "invalid", "localhost"})
RESERVED_DOMAINS: Final = ("example.com", "example.net", "example.org")
NOREPLY_DOMAIN: Final = "users.noreply.github.com"
MIN_TOKEN_LENGTH: Final = 4
DENYLIST_ENVIRONMENT: Final = "ALEXIA_API_DENYLIST"
DEFAULT_DENYLIST: Final = ".denylist.sha256"
SKIPPED_FILES: Final = frozenset({"pixi.lock"})
SKIPPED_DIRECTORIES: Final = frozenset(
    {
        ".git",
        ".pixi",
        ".venv",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".hypothesis",
        ".coverage",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
    }
)


def tokenize(text: str) -> list[str]:
    """Lower-case words of at least four letters, with accents removed."""
    decomposed = unicodedata.normalize("NFD", text)
    folded = "".join(c for c in decomposed if not unicodedata.category(c).startswith("M")).lower()
    return [word for word in re.split(r"[^a-z]+", folded) if len(word) >= MIN_TOKEN_LENGTH]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def load_denylist(path: Path) -> frozenset[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip() for line in lines if line.strip())


def is_safe_email_domain(domain: str) -> bool:
    """Whether nobody can own an address at this domain."""
    name = domain.lower().rstrip(".")
    if name.rsplit(".", 1)[-1] in RESERVED_TOP_LEVEL_NAMES or name == NOREPLY_DOMAIN:
        return True
    return any(name == reserved or name.endswith(f".{reserved}") for reserved in RESERVED_DOMAINS)


def problems_in(line: str, denylist: frozenset[str] | None) -> list[str]:
    found: list[str] = []
    found.extend(
        "GUID outside the synthetic range"
        for match in GUID.finditer(line)
        if not SYNTHETIC_GUID.fullmatch(match.group(0))
    )
    found.extend(
        "email outside the safe domains"
        for match in EMAIL.finditer(line)
        if not is_safe_email_domain(match.group(1))
    )
    if denylist is not None and any(hash_token(word) in denylist for word in tokenize(line)):
        found.append("word from the local denylist")
    return found


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(  # noqa: S603
            ["git", "-C", str(root), *arguments],  # noqa: S607
            check=False,
            capture_output=True,
        )
    except OSError:
        return None


def _git_files(root: Path) -> list[Path] | None:
    result = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if result is None or result.returncode != 0:
        return None
    return [root / name for name in result.stdout.decode().split("\0") if name]


def _walk(root: Path) -> Iterator[Path]:
    for directory, names, files in os.walk(root):
        names[:] = [name for name in names if name not in SKIPPED_DIRECTORIES]
        for name in files:
            yield Path(directory) / name


def files_under(root: Path) -> Iterator[Path]:
    """Files git would track, or every file under the folder when it is not a git checkout."""
    listed = _git_files(root)
    candidates = listed if listed is not None else _walk(root)
    for path in candidates:
        if path.name not in SKIPPED_FILES and not SKIPPED_DIRECTORIES.intersection(path.parts):
            yield path


def scan(root: Path, denylist: frozenset[str] | None) -> tuple[list[str], int]:
    """Return the violations and how many text files were read."""
    violations: list[str] = []
    scanned = 0
    for path in files_under(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        relative = path.relative_to(root)
        for number, line in enumerate(text.splitlines(), start=1):
            violations.extend(f"{relative}:{number} {rule}" for rule in problems_in(line, denylist))
    return violations, scanned


def scan_history(
    root: Path, denylist: frozenset[str] | None, *, all_refs: bool = False
) -> tuple[list[str], int]:
    """Check every line any commit added. Returns the violations and the commit count."""
    revisions = ["--branches", "--tags", "--remotes"] if all_refs else ["HEAD"]
    result = _git(
        root, "log", *revisions, "-p", "--no-color", "--no-ext-diff", "--format=commit %h"
    )
    if result is None or result.returncode != 0:
        return [], 0
    violations: list[str] = []
    commits = 0
    sha = ""
    path = ""
    number = 0
    in_header = False
    for raw in result.stdout.decode("utf-8", errors="replace").split("\n"):
        if raw.startswith("commit "):
            sha = raw.removeprefix("commit ")
            commits += 1
            in_header = False
        elif raw.startswith("diff --git "):
            in_header = True
        elif in_header and raw.startswith("+++ "):
            target = raw.removeprefix("+++ ")
            path = "" if target == "/dev/null" else target.removeprefix("b/")
        elif raw.startswith("@@"):
            in_header = False
            hunk = HUNK.match(raw)
            number = int(hunk.group(1)) if hunk else 0
        elif not in_header and raw.startswith("+"):
            violations.extend(
                f"{sha}:{path}:{number} {rule}" for rule in problems_in(raw[1:], denylist)
            )
            number += 1
        elif not in_header and raw.startswith(" "):
            number += 1
    return violations, commits


def _resolve_denylist(root: Path, option: Path | None) -> frozenset[str] | None:
    chosen = option
    if chosen is None and os.environ.get(DENYLIST_ENVIRONMENT):
        chosen = Path(os.environ[DENYLIST_ENVIRONMENT])
    if chosen is None and (root / DEFAULT_DENYLIST).is_file():
        chosen = root / DEFAULT_DENYLIST
    return load_denylist(chosen) if chosen is not None else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail when a file holds real personal data.")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd(), help="folder to scan")
    parser.add_argument("--denylist", type=Path, help="file of SHA-256 digests of protected words")
    parser.add_argument(
        "--history", action="store_true", help="also check every commit in the checked-out history"
    )
    parser.add_argument(
        "--all-refs",
        action="store_true",
        help="also check every commit on every branch, tag, and remote branch",
    )
    arguments = parser.parse_args(argv)

    root = arguments.root.resolve()
    denylist = _resolve_denylist(root, arguments.denylist)
    violations, scanned = scan(root, denylist)
    commits = 0
    with_history = arguments.history or arguments.all_refs
    if with_history:
        past, commits = scan_history(root, denylist, all_refs=arguments.all_refs)
        violations.extend(past)

    where = f"{scanned} file(s)" + (f" and {commits} commit(s)" if with_history else "")
    if violations:
        sys.stderr.write("\n".join(violations) + "\n")
        sys.stderr.write(f"check_privacy failed, {len(violations)} problem(s) in {where}\n")
        return 1
    note = f"denylist={len(denylist)}" if denylist is not None else "denylist=absent"
    history = f" commits={commits}" if with_history else ""
    sys.stdout.write(f"check_privacy ok files={scanned}{history} {note}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
