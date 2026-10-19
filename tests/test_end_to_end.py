"""The demo, started the way a person starts it and asked over a real socket.

Every other test calls the server inside the test process. These tests start the installed
`alexia-api` command as a process of its own. They show that the command starts, that the banner
tells the truth, and that ending the process leaves nothing behind.
"""

import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from alexia_api.demo import ENDING_SIGNALS, TOUR, Suggestion

pytestmark = pytest.mark.e2e

START_SECONDS = 60.0
END_SECONDS = 30.0
REQUEST_SECONDS = 10.0
KEY_LINE = re.compile(r"^ {4}(afk_[A-Za-z0-9_-]+)$", re.MULTILINE)
CALENDAR_LINE = re.compile(r"^ {4}(http://\S+\?key=afk_[A-Za-z0-9_-]+)$", re.MULTILINE)
MEDIA_TYPE_OF_FILE = {".pdf": "application/pdf", ".ics": "text/calendar"}
ENDINGS = [] if sys.platform == "win32" else [signal.SIGINT, *ENDING_SIGNALS]


@dataclass(frozen=True)
class Running:
    """A demo process that answers, with what its banner told a person."""

    base: str
    key: str
    calendar_address: str
    banner: str
    process: subprocess.Popen[bytes]
    scratch: Path
    standard_output: Path
    standard_error: Path

    def get(self, path: str, key: str | None = None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        return httpx.get(f"{self.base}{path}", headers=headers, timeout=REQUEST_SECONDS)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _command() -> str:
    found = shutil.which("alexia-api", path=str(Path(sys.executable).parent))
    assert found is not None, "install the package, so that the alexia-api command exists"
    return found


def _wait_until_it_answers(
    base: str, process: subprocess.Popen[bytes], standard_error: Path
) -> None:
    deadline = time.monotonic() + START_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            said = standard_error.read_text(encoding="utf-8", errors="replace")
            pytest.fail(
                f"the demo ended with status {process.returncode} before it answered\n{said}"
            )
        try:
            httpx.get(f"{base}/healthz", timeout=1.0).raise_for_status()
        except httpx.TransportError:
            time.sleep(0.05)
        else:
            return
    pytest.fail(f"the demo did not answer within {START_SECONDS:.0f} seconds")


@contextmanager
def demo_process(folder: Path) -> Iterator[Running]:
    """Start `alexia-api demo` on a free port, with a temporary folder of its own."""
    scratch = folder / "scratch"
    scratch.mkdir()
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("ALEXIA_API_")
    }
    environment.update(TMPDIR=str(scratch), TMP=str(scratch), TEMP=str(scratch))
    standard_output = folder / "standard-output.txt"
    standard_error = folder / "standard-error.txt"
    with standard_output.open("wb") as out, standard_error.open("wb") as err:
        process = subprocess.Popen(  # noqa: S603
            [_command(), "demo", "--port", str(port)], stdout=out, stderr=err, env=environment
        )
        try:
            _wait_until_it_answers(base, process, standard_error)
            banner = standard_error.read_text(encoding="utf-8")
            key = KEY_LINE.search(banner)
            calendar = CALENDAR_LINE.search(banner)
            assert key is not None, "the banner shows no key"
            assert calendar is not None, "the banner shows no calendar address"
            yield Running(
                base=base,
                key=key.group(1),
                calendar_address=calendar.group(1),
                banner=banner,
                process=process,
                scratch=scratch,
                standard_output=standard_output,
                standard_error=standard_error,
            )
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=END_SECONDS)


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Running]:
    with demo_process(tmp_path_factory.mktemp("demo")) as running:
        yield running


def _media_type_of(suggestion: Suggestion) -> str:
    suffix = Path(suggestion.save_as or "").suffix
    return MEDIA_TYPE_OF_FILE.get(suffix, "application/json")


@pytest.mark.parametrize("suggestion", TOUR, ids=lambda suggestion: suggestion.path)
def test_every_request_the_banner_suggests_is_answered_with_the_key_it_shows(
    demo: Running, suggestion: Suggestion
) -> None:
    command = f'curl -H "Authorization: Bearer {demo.key}" "{demo.base}{suggestion.path}"'
    response = demo.get(suggestion.path, demo.key)

    assert command in demo.banner
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(_media_type_of(suggestion))


def test_the_documentation_address_in_the_banner_opens_the_documentation(demo: Running) -> None:
    response = demo.get("/docs")

    assert f"{demo.base}/docs" in demo.banner
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_the_address_the_banner_gives_a_calendar_app_opens_a_calendar(demo: Running) -> None:
    response = httpx.get(demo.calendar_address, timeout=REQUEST_SECONDS)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert response.headers["cache-control"] == "no-store"
    assert response.text.startswith("BEGIN:VCALENDAR")


def test_the_key_in_the_calendar_address_opens_calendars_and_nothing_else(demo: Running) -> None:
    calendar_key = demo.calendar_address.rsplit("key=", 1)[1]

    response = demo.get("/v1/accounts", calendar_key)

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


def test_a_request_without_a_key_is_refused_with_a_problem_document(demo: Running) -> None:
    response = demo.get("/v1/accounts")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert response.json()["code"] == "missing_api_key"


def test_an_account_that_does_not_exist_is_not_found(demo: Running) -> None:
    response = demo.get("/v1/accounts/nobody/children", demo.key)

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_the_banner_goes_to_standard_error_and_standard_output_stays_empty(demo: Running) -> None:
    assert demo.banner.startswith("The demo is running against a simulated school.")
    assert demo.standard_output.read_bytes() == b""


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot send these signals")
@pytest.mark.parametrize("ending", ENDINGS, ids=lambda ending: ending.name)
def test_the_demo_shuts_down_in_order_and_removes_its_state_when_asked_to_end(
    tmp_path: Path, ending: signal.Signals
) -> None:
    with demo_process(tmp_path) as running:
        assert len(list(running.scratch.glob("alexia-demo-*"))) == 1
        running.process.send_signal(ending)
        status = running.process.wait(timeout=END_SECONDS)

    said = running.standard_error.read_text(encoding="utf-8")
    assert status == (0 if ending == signal.SIGINT else 128 + signal.SIGTERM)
    assert list(running.scratch.iterdir()) == []
    assert "Application shutdown complete." in said
    assert "Traceback" not in said
