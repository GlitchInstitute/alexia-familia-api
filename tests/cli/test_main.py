"""The command line lists its commands, reports its version, and starts nothing by itself."""

import re
from itertools import pairwise

import pytest

from alexia_api import __version__
from tests.cli.conftest import UvicornCall
from tests.cli.support import run

COMMANDS = ("init", "doctor", "serve", "keys", "accounts")
SCREENS = (
    ("init",),
    ("doctor",),
    ("serve",),
    ("keys",),
    ("keys", "create"),
    ("keys", "list"),
    ("keys", "revoke"),
    ("accounts",),
    ("accounts", "list"),
    ("accounts", "reset"),
)
HEADINGS = {"Arguments:", "Options:", "Commands:"}
SCREEN = {"COLUMNS": "80"}
HELP_WIDTH = 78


def description_paragraphs(help_text: str) -> list[list[str]]:
    """The paragraphs between the usage line and the first heading, as the screen shows them."""
    lines = help_text.splitlines()
    assert "Options:" in lines, "the help should be plain text with an Options heading"
    first = next(number for number, line in enumerate(lines) if line.startswith("Usage:")) + 1
    last = next(number for number, line in enumerate(lines) if line in HEADINGS)
    paragraphs: list[list[str]] = [[]]
    for line in lines[first:last]:
        if line.strip():
            paragraphs[-1].append(line)
        elif paragraphs[-1]:
            paragraphs.append([])
    return [paragraph for paragraph in paragraphs if paragraph]


def test_without_arguments_it_lists_the_commands_in_the_order_a_newcomer_needs_them(
    uvicorn_calls: list[UvicornCall],
) -> None:
    result = run()

    listed = [
        line.split()[0]
        for line in result.output.partition("Commands:")[2].splitlines()
        if line.startswith("  ") and not line.startswith("   ")
    ]
    assert listed == list(COMMANDS)
    assert uvicorn_calls == []


def test_version_prints_the_package_version(uvicorn_calls: list[UvicornCall]) -> None:
    result = run("--version")

    assert result.exit_code == 0
    assert result.output.strip() == f"alexia-api {__version__}"
    assert uvicorn_calls == []


def test_a_mistyped_command_is_a_usage_error(uvicorn_calls: list[UvicornCall]) -> None:
    result = run("servee")

    assert result.exit_code == 2
    assert "No such command 'servee'" in result.stderr
    assert uvicorn_calls == []


def test_the_only_options_before_a_command_are_the_version_and_the_help() -> None:
    result = run("--help")

    options = result.output.partition("Options:")[2].partition("Commands:")[0]
    assert re.findall(r"^  (--[a-z-]+)", options, re.MULTILINE) == ["--version", "--help"]


@pytest.mark.parametrize("screen", SCREENS, ids=" ".join)
def test_every_command_explains_itself(screen: tuple[str, ...]) -> None:
    result = run(*screen, "--help")

    assert result.exit_code == 0
    assert f"alexia-api {' '.join(screen)}" in result.output


@pytest.mark.parametrize("screen", SCREENS, ids=" ".join)
def test_help_paragraphs_fill_the_width_of_the_screen(screen: tuple[str, ...]) -> None:
    result = run(*screen, "--help", env=SCREEN)

    paragraphs = description_paragraphs(result.output)
    assert paragraphs
    for paragraph in paragraphs:
        for above, below in pairwise(paragraph):
            assert len(above) + 1 + len(below.split()[0]) > HELP_WIDTH, f"{above!r} ends early"
