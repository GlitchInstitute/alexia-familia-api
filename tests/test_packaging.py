import re
import shlex
import tomllib
from pathlib import Path

import pytest
import typer.main

from alexia_api import __version__, cli
from tests.cli.support import run

ROOT = Path(__file__).resolve().parent.parent
CONDA_NAME_FOR = {"fastapi": "fastapi-core", "tzdata": "python-tzdata"}
LOWER_BOUND = re.compile(r">=\s*([0-9][0-9.]*)")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def _load(name: str) -> dict[str, object]:
    return tomllib.loads((ROOT / name).read_text(encoding="utf-8"))


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split(".") if part)


def _pyproject_requirements() -> dict[str, tuple[int, ...] | None]:
    project = _load("pyproject.toml")["project"]
    assert isinstance(project, dict)
    found: dict[str, tuple[int, ...] | None] = {}
    for requirement in project["dependencies"]:
        name_match = NAME.match(requirement)
        assert name_match is not None, requirement
        bound = LOWER_BOUND.search(requirement)
        found[name_match.group(0).lower()] = _version_tuple(bound.group(1)) if bound else None
    return found


def _pixi_dependencies() -> dict[str, str]:
    dependencies = _load("pixi.toml")["dependencies"]
    assert isinstance(dependencies, dict)
    return {str(name): str(spec) for name, spec in dependencies.items()}


def test_every_runtime_dependency_is_installed_by_pixi_with_the_same_floor() -> None:
    pixi = _pixi_dependencies()
    for name, floor in _pyproject_requirements().items():
        conda_name = CONDA_NAME_FOR.get(name, name)
        assert conda_name in pixi, f"{name} is in pyproject.toml but not in pixi.toml"
        if floor is None:
            continue
        pixi_bound = LOWER_BOUND.search(pixi[conda_name])
        assert pixi_bound is not None, f"{conda_name} has no lower bound in pixi.toml"
        assert _version_tuple(pixi_bound.group(1)) >= floor, name


def test_the_workspace_version_matches_the_package_version() -> None:
    workspace = _load("pixi.toml")["workspace"]
    assert isinstance(workspace, dict)
    assert workspace["version"] == __version__


def _alexia_tasks() -> dict[str, str]:
    tasks = _load("pixi.toml")["tasks"]
    assert isinstance(tasks, dict)
    commands: dict[str, str] = {}
    for name, task in tasks.items():
        assert isinstance(task, dict)
        if str(task["cmd"]).startswith("alexia-api"):
            commands[str(name)] = str(task["cmd"])
    return commands


ALEXIA_TASKS = _alexia_tasks()


def test_every_command_has_a_pixi_task_of_the_same_name() -> None:
    commands = set(typer.main.get_group(cli.app).commands)

    assert set(ALEXIA_TASKS) == commands


@pytest.mark.parametrize("name", ALEXIA_TASKS)
def test_every_pixi_task_runs_a_command_that_exists(name: str) -> None:
    result = run(*shlex.split(ALEXIA_TASKS[name])[1:], "--help")

    assert result.exit_code == 0, f"the task {name} runs `{ALEXIA_TASKS[name]}`, which fails"
