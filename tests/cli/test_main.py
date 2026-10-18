"""The command line starts the server with the options it was given."""

from typing import Any

import pytest
import uvicorn
from typer.testing import CliRunner

from alexia_api import __version__, cli

runner = CliRunner()
type Call = tuple[tuple[Any, ...], dict[str, Any]]


@pytest.fixture
def uvicorn_calls(monkeypatch: pytest.MonkeyPatch) -> list[Call]:
    calls: list[Call] = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    return calls


def test_without_arguments_it_lists_the_commands_and_starts_nothing(
    uvicorn_calls: list[Call],
) -> None:
    result = runner.invoke(cli.app, [])

    assert "serve" in result.output
    assert uvicorn_calls == []


def test_version_prints_the_package_version(uvicorn_calls: list[Call]) -> None:
    result = runner.invoke(cli.app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"alexia-api {__version__}"
    assert uvicorn_calls == []


def test_serve_listens_on_the_loopback_address_by_default(uvicorn_calls: list[Call]) -> None:
    result = runner.invoke(cli.app, ["serve"])

    assert result.exit_code == 0
    assert uvicorn_calls == [
        (
            ("alexia_api.api.app:create_app",),
            {"factory": True, "host": "127.0.0.1", "port": 8000, "reload": False},
        )
    ]


def test_serve_passes_its_options_to_uvicorn(uvicorn_calls: list[Call]) -> None:
    result = runner.invoke(cli.app, ["serve", "--host", "127.0.0.2", "--port", "9000", "--reload"])

    assert result.exit_code == 0
    assert uvicorn_calls[0][1] == {
        "factory": True,
        "host": "127.0.0.2",
        "port": 9000,
        "reload": True,
    }
