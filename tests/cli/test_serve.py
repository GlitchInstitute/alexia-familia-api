"""The serve command runs the doctor's checks, then starts the server it was asked for."""

import re
from pathlib import Path

from alexia_api.config import CONFIG_ENV
from alexia_api.logs import log_config
from tests.cli.conftest import UvicornCall
from tests.cli.support import run
from tests.workspace import ENVIRON, make_key, write_config

TARGET = "alexia_api.api.app:create_app"
CANNOT_START = "The server cannot start. Fix the lines marked stop and run this again."


def test_a_healthy_setup_starts_the_server_without_a_word(
    tmp_path: Path, uvicorn_calls: list[UvicornCall]
) -> None:
    path = write_config(tmp_path)
    make_key(tmp_path)

    result = run("serve", "--config", str(path), env=ENVIRON)

    assert result.exit_code == 0
    assert result.output == ""
    assert [(call.target, call.options) for call in uvicorn_calls] == [
        (
            TARGET,
            {
                "factory": True,
                "host": "127.0.0.1",
                "port": 8000,
                "reload": False,
                "log_config": log_config("info", "text"),
            },
        )
    ]


def test_the_options_reach_uvicorn(tmp_path: Path, uvicorn_calls: list[UvicornCall]) -> None:
    path = write_config(tmp_path)
    make_key(tmp_path)

    result = run(
        "serve",
        "--config",
        str(path),
        "--host",
        "127.0.0.2",
        "--port",
        "9000",
        "--reload",
        env=ENVIRON,
    )

    [call] = uvicorn_calls
    assert result.exit_code == 0
    assert (call.options["host"], call.options["port"], call.options["reload"]) == (
        "127.0.0.2",
        9000,
        True,
    )


def test_the_log_settings_reach_uvicorn(tmp_path: Path, uvicorn_calls: list[UvicornCall]) -> None:
    path = write_config(tmp_path, top='log_level = "debug"\nlog_format = "json"')
    make_key(tmp_path)

    run("serve", "--config", str(path), env=ENVIRON)

    [call] = uvicorn_calls
    assert call.options["log_config"] == log_config("debug", "json")


def test_the_file_is_handed_to_the_server_through_the_environment(
    tmp_path: Path, uvicorn_calls: list[UvicornCall]
) -> None:
    path = write_config(tmp_path)
    make_key(tmp_path)

    run("serve", "--config", str(path), env={**ENVIRON, CONFIG_ENV: None})

    [call] = uvicorn_calls
    assert call.config_variable == str(path.resolve())


def test_a_file_found_in_the_current_folder_needs_no_variable(
    workdir: Path, uvicorn_calls: list[UvicornCall]
) -> None:
    write_config(workdir)
    make_key(workdir)

    result = run("serve", env={**ENVIRON, CONFIG_ENV: None})

    [call] = uvicorn_calls
    assert result.exit_code == 0
    assert call.config_variable is None


def test_a_stop_keeps_the_server_from_starting(uvicorn_calls: list[UvicornCall]) -> None:
    result = run("serve")

    assert result.exit_code == 1
    assert uvicorn_calls == []
    assert result.stdout == ""
    assert "stop  accounts  no account is configured" in result.stderr
    assert result.stderr.endswith(f"{CANNOT_START}\n")


def test_a_missing_secret_keeps_the_server_from_starting_and_names_the_variable(
    tmp_path: Path, uvicorn_calls: list[UvicornCall]
) -> None:
    path = write_config(tmp_path)
    make_key(tmp_path)

    result = run("serve", "--config", str(path))

    assert result.exit_code == 1
    assert uvicorn_calls == []
    assert "MARTA_USER" in result.stderr
    assert result.stderr.endswith(f"{CANNOT_START}\n")


def test_a_configuration_error_keeps_the_server_from_starting(
    tmp_path: Path, uvicorn_calls: list[UvicornCall]
) -> None:
    path = write_config(tmp_path, top="nonsense = 1")

    result = run("serve", "--config", str(path), env=ENVIRON)

    assert result.exit_code == 1
    assert uvicorn_calls == []
    assert "nonsense" in result.stderr


def test_a_failure_is_shown_and_the_server_starts_anyway(
    tmp_path: Path, uvicorn_calls: list[UvicornCall]
) -> None:
    path = write_config(tmp_path)

    result = run("serve", "--config", str(path), env=ENVIRON)

    assert result.exit_code == 0
    assert len(uvicorn_calls) == 1
    assert result.stdout == ""
    assert "fail  keys  no API key exists, so every request would be refused" in result.stderr
    assert "Fix: run `alexia-api keys create NAME`" in result.stderr
    assert result.stderr.splitlines()[-2:] == [
        "",
        "The server can start, but the lines marked fail need attention.",
    ]


def test_a_caution_is_shown_and_the_server_starts(
    tmp_path: Path, uvicorn_calls: list[UvicornCall]
) -> None:
    path = write_config(tmp_path, top="allow_writes = true")
    make_key(tmp_path)

    result = run("serve", "--config", str(path), env=ENVIRON)

    assert result.exit_code == 0
    assert len(uvicorn_calls) == 1
    assert "switched on, writes" in result.stderr
    assert result.stderr.endswith("Nothing is broken, but read the lines marked warn.\n")


def test_lines_that_are_fine_are_not_repeated_at_start(
    tmp_path: Path, uvicorn_calls: list[UvicornCall]
) -> None:
    path = write_config(tmp_path)

    result = run("serve", "--config", str(path), env=ENVIRON)

    assert len(uvicorn_calls) == 1
    assert re.search(r"^ok ", result.stderr, re.MULTILINE) is None


def test_no_secret_is_printed(tmp_path: Path, uvicorn_calls: list[UvicornCall]) -> None:
    path = write_config(tmp_path)

    result = run("serve", "--config", str(path), env=ENVIRON)

    assert len(uvicorn_calls) == 1
    for secret in ENVIRON.values():
        assert secret not in result.output
