"""The doctor command shows what the checks found, and its exit status says whether to worry."""

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from alexia_api.cli import main
from alexia_api.config import Settings
from alexia_api.doctor import Finding
from tests.cli.support import run
from tests.workspace import ENVIRON, make_key, write_config

ANSWERS_IN_TIME = Finding("ok", "portal.marta", "the login page answers in 12 ms")


@dataclass
class Probes:
    """The portals the doctor asked about, and the answer the next question gets."""

    asked: list[Settings] = field(default_factory=list)
    answer: tuple[Finding, ...] = (ANSWERS_IN_TIME,)


@pytest.fixture
def probes(monkeypatch: pytest.MonkeyPatch) -> Probes:
    probes = Probes()

    async def answer(settings: Settings) -> tuple[Finding, ...]:
        probes.asked.append(settings)
        return probes.answer

    monkeypatch.setattr(main, "probe_portals", answer)
    return probes


def test_a_healthy_setup_is_all_ok_and_exits_cleanly(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    make_key(tmp_path)

    result = run("doctor", "--config", str(path), env=ENVIRON)

    lines = result.stdout.splitlines()
    assert result.exit_code == 0
    assert result.stderr == ""
    assert all(line.startswith("ok  ") for line in lines[:-2])
    assert f"read {path.resolve()}" in lines[0]
    assert lines[-2:] == ["", "Everything checks out."]


def test_a_missing_key_fails_the_check_and_names_the_command_that_fixes_it(
    tmp_path: Path,
) -> None:
    path = write_config(tmp_path)

    result = run("doctor", "--config", str(path), env=ENVIRON)

    assert result.exit_code == 1
    assert "Fix: run `alexia-api keys create NAME`" in result.stdout
    assert result.stdout.endswith(
        "The server can start, but the lines marked fail need attention.\n"
    )


def test_nothing_configured_stops_the_check_and_points_at_init_and_the_demo() -> None:
    result = run("doctor")

    assert result.exit_code == 1
    assert "stop  accounts  no account is configured" in result.stdout
    assert "alexia-api init" in result.stdout
    assert "alexia-api demo" in result.stdout
    assert result.stdout.endswith(
        "The server cannot start. Fix the lines marked stop and run this again.\n"
    )


def test_a_caution_alone_does_not_fail_the_check(tmp_path: Path) -> None:
    path = write_config(tmp_path, top="allow_writes = true")
    make_key(tmp_path)

    result = run("doctor", "--config", str(path), env=ENVIRON)

    assert result.exit_code == 0
    assert "switched on, writes, so a key with the write scope can act as you" in result.stdout
    assert "Fix: keep these off unless you need them" in result.stdout
    assert result.stdout.endswith("Nothing is broken, but read the lines marked warn.\n")


def test_a_configuration_file_that_does_not_exist_stops_the_check(tmp_path: Path) -> None:
    result = run("doctor", "--config", str(tmp_path / "missing.toml"))

    assert result.exit_code == 1
    assert "does not exist" in result.stdout


def test_the_file_in_the_current_folder_is_found_without_the_option(workdir: Path) -> None:
    path = write_config(workdir)
    make_key(workdir)

    result = run("doctor", env=ENVIRON)

    assert result.exit_code == 0
    assert f"read {path.resolve()}" in result.stdout


def test_a_relative_file_name_is_shown_in_full(workdir: Path) -> None:
    path = write_config(workdir)
    make_key(workdir)

    result = run("doctor", "--config", path.name, env=ENVIRON)

    assert result.exit_code == 0
    assert f"read {path.resolve()}" in result.stdout


def test_the_environment_can_name_the_file(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    make_key(tmp_path)

    result = run("doctor", env={**ENVIRON, "ALEXIA_API_CONFIG": str(path)})

    assert result.exit_code == 0
    assert f"read {path.resolve()}" in result.stdout


def test_no_secret_is_printed(tmp_path: Path) -> None:
    path = write_config(tmp_path)

    result = run("doctor", "--config", str(path), env=ENVIRON)

    for secret in ENVIRON.values():
        assert secret not in result.output


def test_online_adds_what_the_portals_answered(tmp_path: Path, probes: Probes) -> None:
    path = write_config(tmp_path)
    make_key(tmp_path)

    result = run("doctor", "--config", str(path), "--online", env=ENVIRON)

    lines = result.stdout.splitlines()
    assert result.exit_code == 0
    assert f"read {path.resolve()}" in lines[0]
    assert lines[-3].endswith("the login page answers in 12 ms")
    assert [list(settings.accounts) for settings in probes.asked] == [["marta"]]


def test_a_portal_that_does_not_answer_fails_the_check(tmp_path: Path, probes: Probes) -> None:
    probes.answer = (
        Finding("fail", "portal.marta", "the portal does not answer", "check the address"),
    )
    path = write_config(tmp_path)
    make_key(tmp_path)

    result = run("doctor", "--config", str(path), "--online", env=ENVIRON)

    assert result.exit_code == 1
    assert "Fix: check the address" in result.stdout


def test_no_portal_is_asked_without_the_online_option(tmp_path: Path, probes: Probes) -> None:
    path = write_config(tmp_path)
    make_key(tmp_path)

    run("doctor", "--config", str(path), env=ENVIRON)

    assert probes.asked == []


def test_no_portal_is_asked_when_the_settings_cannot_be_read(
    tmp_path: Path, probes: Probes
) -> None:
    result = run("doctor", "--config", str(tmp_path / "missing.toml"), "--online")

    assert result.exit_code == 1
    assert probes.asked == []
