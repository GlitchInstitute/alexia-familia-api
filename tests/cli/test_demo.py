"""The demo command starts the server against a simulated school and shows how to use it."""

import asyncio
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from alexia_api.cli import main
from alexia_api.demo import CALENDAR_PATH, ENDING_SIGNALS, TOUR, banner
from alexia_api.logs import log_config
from tests.cli.conftest import UvicornCall
from tests.cli.support import run


@dataclass
class Asked:
    """What the stand-in for uvicorn saw while the demo was running."""

    status: int | None = None
    calendar_status: int | None = None
    state_dir: Path | None = None
    existed: bool | None = None


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> Asked:
    """Replace uvicorn with a stand-in that asks the server a question with each key shown."""
    shown: list[tuple[str, str]] = []

    def spy(base: str, key: str, calendar_key: str, *, windows: bool = False) -> str:
        shown.append((key, calendar_key))
        return banner(base, key, calendar_key, windows=windows)

    async def ask(app: FastAPI) -> tuple[int, int]:
        key, calendar_key = shown[0]
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://demo.test") as client:
            accounts = await client.get("/v1/accounts", headers={"Authorization": f"Bearer {key}"})
            calendar = await client.get(CALENDAR_PATH, params={"key": calendar_key})
        await app.state.services.registry.aclose()
        return accounts.status_code, calendar.status_code

    seen = Asked()

    def serve(app: FastAPI, **_options: Any) -> None:
        seen.state_dir = app.state.services.settings.state_dir
        seen.existed = seen.state_dir.exists()
        seen.status, seen.calendar_status = asyncio.run(ask(app))

    monkeypatch.setattr(main, "banner", spy)
    monkeypatch.setattr(uvicorn, "run", serve)
    return seen


def test_it_starts_the_server_on_the_usual_address(uvicorn_calls: list[UvicornCall]) -> None:
    result = run("demo")

    [call] = uvicorn_calls
    assert result.exit_code == 0
    assert isinstance(call.target, FastAPI)
    assert (call.options["host"], call.options["port"]) == ("127.0.0.1", 8000)


def test_the_banner_is_a_notice_so_standard_output_stays_empty(
    uvicorn_calls: list[UvicornCall],
) -> None:
    result = run("demo")

    assert result.stdout == ""
    assert result.stderr.startswith("The demo is running against a simulated school.")
    assert "http://127.0.0.1:8000/docs" in result.stderr
    assert result.stderr.count("curl -H") == len(TOUR)
    assert result.stderr.endswith("Press Ctrl+C to stop.\n\n")


def test_the_key_the_banner_shows_opens_the_server_while_it_runs(asked: Asked) -> None:
    run("demo")

    assert asked.status == 200


def test_the_address_the_banner_gives_a_calendar_app_opens_a_calendar_while_it_runs(
    asked: Asked,
) -> None:
    run("demo")

    assert asked.calendar_status == 200


def test_the_state_folder_exists_while_the_demo_runs_and_is_gone_afterwards(asked: Asked) -> None:
    run("demo")

    assert asked.state_dir is not None
    assert asked.existed is True
    assert not asked.state_dir.exists()


def test_the_folder_is_removed_even_when_the_server_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folders: list[Path] = []

    def refuse(app: FastAPI, **_options: Any) -> None:
        folders.append(app.state.services.settings.state_dir)
        raise SystemExit(1)

    monkeypatch.setattr(uvicorn, "run", refuse)

    result = run("demo")

    assert result.exit_code == 1
    assert not folders[0].exists()


@pytest.mark.parametrize("ending", ENDING_SIGNALS, ids=lambda ending: ending.name)
def test_the_folder_is_removed_and_the_exit_says_terminated_when_the_server_is_told_to_end(
    monkeypatch: pytest.MonkeyPatch, ending: signal.Signals
) -> None:
    folders: list[Path] = []

    def told_to_end(app: FastAPI, **_options: Any) -> None:
        folders.append(app.state.services.settings.state_dir)
        signal.raise_signal(ending)

    monkeypatch.setattr(uvicorn, "run", told_to_end)
    before = signal.getsignal(ending)

    result = run("demo")

    assert result.exit_code == 128 + signal.SIGTERM
    assert not folders[0].exists()
    assert signal.getsignal(ending) == before


def test_the_options_choose_where_to_listen_and_the_banner_gives_an_address_to_open(
    uvicorn_calls: list[UvicornCall],
) -> None:
    result = run("demo", "--host", "0.0.0.0", "--port", "9100")

    [call] = uvicorn_calls
    assert (call.options["host"], call.options["port"]) == ("0.0.0.0", 9100)
    assert "http://localhost:9100/docs" in result.stderr


def test_neither_a_configuration_file_nor_the_variables_are_read(
    workdir: Path, uvicorn_calls: list[UvicornCall]
) -> None:
    (workdir / "alexia-api.toml").write_text("this is not toml", encoding="utf-8")

    result = run("demo", env={"ALEXIA_API_BOGUS": "1"})

    assert result.exit_code == 0
    assert len(uvicorn_calls) == 1


def test_the_server_logs_the_way_the_demo_settings_say(uvicorn_calls: list[UvicornCall]) -> None:
    run("demo")

    [call] = uvicorn_calls
    settings = call.target.state.services.settings
    assert call.options["log_config"] == log_config(settings.log_level, settings.log_format)


@pytest.mark.parametrize(
    ("platform", "command"), [("linux", "curl"), ("darwin", "curl"), ("win32", "curl.exe")]
)
def test_the_requests_use_the_curl_of_the_platform(
    monkeypatch: pytest.MonkeyPatch,
    uvicorn_calls: list[UvicornCall],
    platform: str,
    command: str,
) -> None:
    monkeypatch.setattr(sys, "platform", platform)

    result = run("demo")

    assert f"    {command} -H" in result.stderr
