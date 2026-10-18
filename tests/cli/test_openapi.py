"""The openapi command prints the document of the REST API with no server and no configuration."""

import json
from pathlib import Path

import pytest

from alexia_api import __version__
from alexia_api.api.app import openapi_document
from alexia_api.cli import main
from alexia_api.config import CONFIG_ENV
from tests.cli.support import run


def test_it_prints_the_document_as_json_on_standard_output() -> None:
    result = run("openapi")

    document = json.loads(result.stdout)
    assert result.exit_code == 0
    assert document["info"]["title"] == "alexia-familia-api"
    assert document["info"]["version"] == __version__
    assert result.stdout.endswith("}\n")
    assert result.stderr == ""


def test_the_text_is_indented_so_a_person_can_read_it_and_a_diff_shows_changes() -> None:
    result = run("openapi")

    assert result.stdout.startswith('{\n  "openapi": "3.1.0",\n  "info": {\n    "title"')


def test_accented_text_is_escaped_so_any_terminal_and_file_encoding_keeps_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "openapi_document", lambda: {"title": "Información"})

    result = run("openapi")

    assert result.stdout == '{\n  "title": "Informaci\\u00f3n"\n}\n'


def test_the_text_is_the_document_the_application_builds() -> None:
    result = run("openapi")

    assert json.loads(result.stdout) == openapi_document()


def test_it_reads_no_configuration() -> None:
    result = run("openapi", env={"ALEXIA_API_LOG_LEVEL": "loud", CONFIG_ENV: "missing.toml"})

    assert result.exit_code == 0
    assert json.loads(result.stdout) == openapi_document()


def test_the_output_option_writes_the_same_text_to_a_file(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"

    result = run("openapi", "--output", str(target))

    assert result.exit_code == 0
    assert result.stdout == ""
    assert result.stderr == f"Wrote {target}.\n"
    assert target.read_text(encoding="utf-8") == run("openapi").stdout


def test_the_file_is_written_with_line_feeds_only_whatever_the_system(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"

    run("openapi", "-o", str(target))

    assert b"\r" not in target.read_bytes()


def test_a_file_that_is_there_is_replaced(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"
    target.write_text("old", encoding="utf-8")

    result = run("openapi", "-o", str(target))

    assert result.exit_code == 0
    assert json.loads(target.read_text(encoding="utf-8")) == openapi_document()


def test_a_tilde_in_the_path_means_the_home_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    result = run("openapi", "-o", "~/openapi.json")

    assert result.exit_code == 0
    assert (tmp_path / "openapi.json").is_file()


def test_a_folder_that_does_not_exist_is_reported_and_nothing_is_printed(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "openapi.json"

    result = run("openapi", "--output", str(target))

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == f"Error: {target} cannot be written, No such file or directory\n"


def test_a_folder_in_place_of_the_file_is_reported(tmp_path: Path) -> None:
    result = run("openapi", "--output", str(tmp_path))

    assert result.exit_code == 1
    assert result.stderr.startswith(f"Error: {tmp_path} cannot be written, ")
    assert "Wrote" not in result.stderr
