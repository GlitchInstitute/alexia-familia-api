#!/usr/bin/env python3
"""Check a release and print its notes.

    python scripts/release_notes.py v0.2.0           print the notes of that release
    python scripts/release_notes.py --check v0.2.0   fail unless the tag, the package, and the
                                                     changelog agree

The release workflow runs the second form before it builds anything, and the first form to fill
the text of the GitHub release. A release depends on three things that people change by hand and
forget: the version in `src/alexia_api/__init__.py`, the version in `pixi.toml`, and a dated
section in `CHANGELOG.md`. A tag that disagrees with any of them is refused.

The script reads only the standard library, so the workflow can run it before any environment
exists.
"""

import argparse
import re
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Final

PACKAGE_FILE: Final = "src/alexia_api/__init__.py"
TAG: Final = re.compile(r"v(\d+\.\d+\.\d+)")
PACKAGE_VERSION: Final = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)
HEADING: Final = re.compile(r"^## \[?([^\]\s]+)\]?(?: - (\d{4}-\d{2}-\d{2}))?\s*$")


class ReleaseError(Exception):
    """The release cannot go out, and the message says what to change."""


def _read(root: Path, name: str) -> str:
    try:
        return (root / name).read_text(encoding="utf-8")
    except OSError:
        raise ReleaseError(f"{name} cannot be read") from None


def version_of(tag: str) -> str:
    """The version a tag names. A tag is the letter v and then three numbers with dots."""
    match = TAG.fullmatch(tag)
    if match is None:
        raise ReleaseError(f"'{tag}' is not a version tag, write it as v1.2.3")
    return match.group(1)


def package_version(root: Path) -> str:
    match = PACKAGE_VERSION.search(_read(root, PACKAGE_FILE))
    if match is None:
        raise ReleaseError(f"{PACKAGE_FILE} has no __version__")
    return match.group(1)


def workspace_version(root: Path) -> str:
    try:
        workspace = tomllib.loads(_read(root, "pixi.toml"))["workspace"]
    except tomllib.TOMLDecodeError:
        raise ReleaseError("pixi.toml is not valid TOML") from None
    except KeyError:
        raise ReleaseError("pixi.toml has no workspace table") from None
    version = workspace.get("version")
    if not isinstance(version, str):
        raise ReleaseError("pixi.toml has no workspace version")
    return version


def notes_for(changelog: str, version: str) -> str:
    """The section of the changelog for one version, without its heading."""
    lines = changelog.splitlines()
    start = date = None
    for number, line in enumerate(lines):
        heading = HEADING.match(line)
        if heading and heading.group(1) == version:
            start, date = number, heading.group(2)
            break
    if start is None:
        raise ReleaseError(f"CHANGELOG.md has no section for {version}")
    if date is None:
        raise ReleaseError(
            f"the section for {version} has no date, "
            f"write its heading as ## [{version}] - YYYY-MM-DD"
        )
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    notes = "\n".join(body).strip()
    if not notes:
        raise ReleaseError(f"the section for {version} has no notes")
    return notes + "\n"


def check(root: Path, tag: str) -> str:
    """Return the version when the tag, the package, the workspace, and the changelog agree."""
    version = version_of(tag)
    package = package_version(root)
    if version != package:
        raise ReleaseError(f"the tag {tag} names {version}, but the package is {package}")
    workspace = workspace_version(root)
    if workspace != package:
        raise ReleaseError(f"pixi.toml is at {workspace}, but the package is {package}")
    notes_for(_read(root, "CHANGELOG.md"), version)
    return version


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a release and print its notes.")
    parser.add_argument("tag", help="the tag of the release, such as v1.2.3")
    parser.add_argument(
        "--check",
        action="store_true",
        help="print nothing but a verdict, and fail unless the tag, the package, and the "
        "changelog agree",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="the folder of the project",
    )
    arguments = parser.parse_args(argv)
    try:
        if arguments.check:
            version = check(arguments.root, arguments.tag)
            sys.stdout.write(f"release_notes ok version={version}\n")
        else:
            notes = notes_for(_read(arguments.root, "CHANGELOG.md"), version_of(arguments.tag))
            sys.stdout.write(notes)
    except ReleaseError as error:
        sys.stderr.write(f"release_notes: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
