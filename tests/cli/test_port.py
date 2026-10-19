"""A command that starts a server says so when the port is taken, before it says anything else.

uvicorn finds out only after the server started, and a banner that says the demo is running would
be wrong by then. The other command-line tests replace the check, so these tests bring it back.
"""

import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import typer

from alexia_api.cli import main, shared
from tests.cli.conftest import UvicornCall
from tests.cli.support import run
from tests.workspace import ENVIRON, make_key, write_config


@contextmanager
def port_in_use() -> Iterator[int]:
    with socket.create_server(("127.0.0.1", 0)) as taken:
        yield taken.getsockname()[1]


@pytest.fixture(autouse=True)
def the_real_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "require_free_port", shared.require_free_port)


def test_the_demo_stops_before_its_banner_when_the_port_is_taken(
    uvicorn_calls: list[UvicornCall],
) -> None:
    with port_in_use() as port:
        result = run("demo", "--port", str(port))

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        f"Error: cannot listen on 127.0.0.1 port {port}, address already in use, "
        "use --port to choose another port\n"
    )
    assert uvicorn_calls == []


def test_the_server_stops_when_the_port_is_taken(
    tmp_path: Path, uvicorn_calls: list[UvicornCall]
) -> None:
    path = write_config(tmp_path)
    make_key(tmp_path)

    with port_in_use() as port:
        result = run("serve", "--config", str(path), "--port", str(port), env=ENVIRON)

    assert result.exit_code == 1
    assert f"cannot listen on 127.0.0.1 port {port}, address already in use" in result.stderr
    assert uvicorn_calls == []


def test_a_setup_that_cannot_start_is_reported_before_the_port(
    uvicorn_calls: list[UvicornCall],
) -> None:
    with port_in_use() as port:
        result = run("serve", "--port", str(port))

    assert result.exit_code == 1
    assert "no account is configured" in result.stderr
    assert "cannot listen" not in result.stderr
    assert uvicorn_calls == []


def test_a_port_that_is_free_passes() -> None:
    shared.require_free_port("127.0.0.1", 0)


def test_an_address_the_machine_cannot_bind_is_refused_in_plain_words() -> None:
    with pytest.raises(typer.Exit):
        shared.require_free_port("203.0.113.7", 0)


def test_an_ipv6_address_is_checked_as_ipv6() -> None:
    try:
        socket.create_server(("::1", 0), family=socket.AF_INET6).close()
    except OSError:
        pytest.skip("this machine has no IPv6 loopback")

    shared.require_free_port("::1", 0)
