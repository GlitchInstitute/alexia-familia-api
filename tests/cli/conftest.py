"""Every command-line test starts in an empty folder, so no file of the developer's is found."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from alexia_api.config import CONFIG_ENV
from tests.workspace import write_config


@dataclass(frozen=True)
class UvicornCall:
    """What a command asked uvicorn to run, and the configuration file the server would see."""

    target: Any
    options: dict[str, Any]
    config_variable: str | None


@pytest.fixture
def uvicorn_calls(monkeypatch: pytest.MonkeyPatch) -> list[UvicornCall]:
    """Replace uvicorn, so a command that would start a server only records the request."""
    calls: list[UvicornCall] = []

    def record(target: Any, **options: Any) -> None:
        calls.append(UvicornCall(target, options, os.environ.get(CONFIG_ENV)))

    monkeypatch.setattr(uvicorn, "run", record)
    return calls


@pytest.fixture(autouse=True)
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The folder the command runs in. It is empty until a test puts a file there."""
    folder = tmp_path / "cwd"
    folder.mkdir()
    monkeypatch.chdir(folder)
    return folder


@pytest.fixture
def config(workdir: Path) -> Path:
    """A healthy configuration file in the working folder, where the commands find it."""
    return write_config(workdir)
