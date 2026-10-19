"""The release script checks that a tag, the package, and the changelog agree."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release_notes.py"

CHANGELOG = """\
# Changelog

This file follows Keep a Changelog.

## Unreleased

- Something that is not released yet.

## [0.2.0] - 2026-11-02

### Added

- A new route.

### Fixed

- A bug.

## [0.1.0] - 2026-10-19

- The first release.
"""

NOTES_OF_0_2_0 = "### Added\n\n- A new route.\n\n### Fixed\n\n- A bug.\n"


def make_project(
    root: Path,
    *,
    version: str = "0.2.0",
    pixi_version: str | None = None,
    changelog: str | None = CHANGELOG,
) -> Path:
    package = root / "src" / "alexia_api"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    shown = pixi_version or version
    (root / "pixi.toml").write_text(
        f'[workspace]\nname = "demo"\nversion = "{shown}"\n', encoding="utf-8"
    )
    if changelog is not None:
        (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return root


def run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--root", str(root), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_notes_of_a_release_are_its_section_of_the_changelog(tmp_path: Path) -> None:
    result = run(make_project(tmp_path), "v0.2.0")

    assert result.returncode == 0
    assert result.stdout == NOTES_OF_0_2_0


def test_the_notes_of_the_oldest_release_run_to_the_end_of_the_file(tmp_path: Path) -> None:
    root = make_project(tmp_path, version="0.1.0")

    result = run(root, "v0.1.0")

    assert result.returncode == 0
    assert result.stdout == "- The first release.\n"


def test_a_check_passes_when_the_tag_the_package_and_the_changelog_agree(tmp_path: Path) -> None:
    result = run(make_project(tmp_path), "--check", "v0.2.0")

    assert result.returncode == 0
    assert result.stdout == "release_notes ok version=0.2.0\n"


@pytest.mark.parametrize("tag", ["0.2.0", "release-2", "v0.2", "v0.2.0-rc.1", "v0.2.0 "])
def test_a_tag_that_is_not_a_version_fails(tmp_path: Path, tag: str) -> None:
    result = run(make_project(tmp_path), "--check", tag)

    assert result.returncode == 1
    assert "is not a version tag" in result.stderr


def test_a_tag_that_names_another_version_than_the_package_fails(tmp_path: Path) -> None:
    result = run(make_project(tmp_path), "--check", "v0.3.0")

    assert result.returncode == 1
    assert "the tag v0.3.0 names 0.3.0, but the package is 0.2.0" in result.stderr


def test_a_workspace_version_that_differs_from_the_package_fails(tmp_path: Path) -> None:
    root = make_project(tmp_path, pixi_version="0.1.9")

    result = run(root, "--check", "v0.2.0")

    assert result.returncode == 1
    assert "pixi.toml is at 0.1.9, but the package is 0.2.0" in result.stderr


def test_a_release_without_a_section_in_the_changelog_fails(tmp_path: Path) -> None:
    root = make_project(tmp_path, version="0.3.0")

    result = run(root, "--check", "v0.3.0")

    assert result.returncode == 1
    assert "CHANGELOG.md has no section for 0.3.0" in result.stderr


def test_a_section_without_a_date_fails(tmp_path: Path) -> None:
    changelog = CHANGELOG.replace("## [0.2.0] - 2026-11-02", "## [0.2.0]")

    result = run(make_project(tmp_path, changelog=changelog), "--check", "v0.2.0")

    assert result.returncode == 1
    assert "the section for 0.2.0 has no date" in result.stderr


def test_a_section_without_notes_fails(tmp_path: Path) -> None:
    changelog = "# Changelog\n\n## [0.2.0] - 2026-11-02\n\n## [0.1.0] - 2026-10-19\n\n- Old.\n"

    result = run(make_project(tmp_path, changelog=changelog), "--check", "v0.2.0")

    assert result.returncode == 1
    assert "the section for 0.2.0 has no notes" in result.stderr


def test_a_heading_without_brackets_is_a_section_too(tmp_path: Path) -> None:
    changelog = "# Changelog\n\n## 0.2.0 - 2026-11-02\n\n- Plain heading.\n"

    result = run(make_project(tmp_path, changelog=changelog), "v0.2.0")

    assert result.returncode == 0
    assert result.stdout == "- Plain heading.\n"


def test_a_missing_changelog_is_reported(tmp_path: Path) -> None:
    result = run(make_project(tmp_path, changelog=None), "--check", "v0.2.0")

    assert result.returncode == 1
    assert "CHANGELOG.md cannot be read" in result.stderr


def test_a_package_without_a_version_is_reported(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    package = root / "src" / "alexia_api" / "__init__.py"
    package.write_text('"""No version."""\n', encoding="utf-8")

    result = run(root, "--check", "v0.2.0")

    assert result.returncode == 1
    assert "has no __version__" in result.stderr


def test_a_workspace_file_that_is_not_toml_is_reported(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    (root / "pixi.toml").write_text("this is [not toml", encoding="utf-8")

    result = run(root, "--check", "v0.2.0")

    assert result.returncode == 1
    assert "pixi.toml is not valid TOML" in result.stderr


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('[tool]\nname = "demo"\n', "pixi.toml has no workspace table"),
        ('[workspace]\nname = "demo"\n', "pixi.toml has no workspace version"),
        ("[workspace]\nversion = 2\n", "pixi.toml has no workspace version"),
    ],
)
def test_a_workspace_that_names_no_version_is_reported(
    tmp_path: Path, text: str, problem: str
) -> None:
    root = make_project(tmp_path)
    (root / "pixi.toml").write_text(text, encoding="utf-8")

    result = run(root, "--check", "v0.2.0")

    assert result.returncode == 1
    assert problem in result.stderr


def test_the_script_run_without_a_tag_says_which_one_it_needs() -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 2
    assert "tag" in result.stderr
