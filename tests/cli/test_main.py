"""The command line lists its commands, reports its version, and starts nothing by itself."""

import pytest

from alexia_api import __version__
from tests.cli.conftest import UvicornCall
from tests.cli.support import run

COMMANDS = ("serve", "doctor")


def test_without_arguments_it_lists_the_commands_and_starts_nothing(
    uvicorn_calls: list[UvicornCall],
) -> None:
    result = run()

    for command in COMMANDS:
        assert command in result.output
    assert uvicorn_calls == []


def test_version_prints_the_package_version(uvicorn_calls: list[UvicornCall]) -> None:
    result = run("--version")

    assert result.exit_code == 0
    assert result.output.strip() == f"alexia-api {__version__}"
    assert uvicorn_calls == []


@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_explains_itself(command: str) -> None:
    result = run(command, "--help")

    assert result.exit_code == 0
    assert f"alexia-api {command}" in result.output
