"""The demo is the real server over a simulated school, so anyone can try it with no setup."""

import signal
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from alexia_api.demo import (
    CALENDAR_PATH,
    ENDING_SIGNALS,
    TOUR,
    Demo,
    Suggestion,
    address,
    banner,
    build_demo,
    demo_state,
)
from alexia_api.services.keys import FILE_NAME

SERVER = "http://demo.test"
KEY = "afk_" + "k" * 43
CALENDAR_KEY = "afk_" + "c" * 43


@asynccontextmanager
async def running(state: Path) -> AsyncIterator[tuple[Demo, httpx.AsyncClient]]:
    demo = build_demo(state)
    transport = httpx.ASGITransport(app=demo.app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url=SERVER) as client:
            yield demo, client
    finally:
        await demo.app.state.services.registry.aclose()


def bearer(demo: Demo) -> dict[str, str]:
    return {"Authorization": f"Bearer {demo.key}"}


@pytest.fixture
async def served(tmp_path: Path) -> AsyncIterator[tuple[Demo, httpx.AsyncClient]]:
    async with running(tmp_path / "state") as pair:
        yield pair


@pytest.mark.parametrize("path", [item.path for item in TOUR])
async def test_every_request_the_demo_suggests_works_with_its_own_key(
    served: tuple[Demo, httpx.AsyncClient], path: str
) -> None:
    demo, client = served

    response = await client.get(path, headers=bearer(demo))

    assert response.status_code == 200


def download_named(name: str) -> Suggestion:
    (download,) = [item for item in TOUR if item.save_as == name]
    return download


async def test_the_attachment_the_demo_suggests_is_a_real_pdf_to_save(
    served: tuple[Demo, httpx.AsyncClient],
) -> None:
    demo, client = served

    response = await client.get(download_named("museo.pdf").path, headers=bearer(demo))

    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert response.headers["content-disposition"].startswith("attachment;")


async def test_the_calendar_the_demo_suggests_is_a_real_file_for_a_calendar_app(
    served: tuple[Demo, httpx.AsyncClient],
) -> None:
    demo, client = served

    response = await client.get(download_named("familia.ics").path, headers=bearer(demo))

    assert response.headers["content-type"] == "text/calendar; charset=utf-8"
    assert response.content.startswith(b"BEGIN:VCALENDAR\r\n")
    assert response.content.endswith(b"END:VCALENDAR\r\n")


def test_the_demo_suggests_exactly_these_files() -> None:
    assert [item.save_as for item in TOUR if item.save_as] == ["museo.pdf", "familia.ics"]


async def test_the_address_for_a_calendar_app_opens_the_calendar_of_the_family(
    served: tuple[Demo, httpx.AsyncClient],
) -> None:
    demo, client = served
    shown = banner(SERVER, demo.key, demo.calendar_key)
    [line] = [line.strip() for line in shown.splitlines() if "?key=" in line]

    response = await client.get(line.removeprefix(SERVER))

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/calendar; charset=utf-8"
    assert b"X-WR-CALNAME:Marta (made up) family school calendar" in response.content


async def test_the_calendar_key_of_the_demo_opens_calendars_and_nothing_else(
    served: tuple[Demo, httpx.AsyncClient],
) -> None:
    demo, client = served
    header = {"Authorization": f"Bearer {demo.calendar_key}"}

    calendar = await client.get(CALENDAR_PATH, headers=header)
    accounts = await client.get("/v1/accounts", headers=header)
    in_an_address = await client.get(f"/v1/accounts?key={demo.calendar_key}")

    assert calendar.status_code == 200
    assert (accounts.status_code, accounts.json()["code"]) == (403, "insufficient_scope")
    assert (in_an_address.status_code, in_an_address.json()["code"]) == (401, "missing_api_key")


async def test_the_demo_key_does_not_travel_in_an_address(
    served: tuple[Demo, httpx.AsyncClient],
) -> None:
    demo, client = served

    response = await client.get(f"{CALENDAR_PATH}?key={demo.key}")

    assert (response.status_code, response.json()["code"]) == (403, "key_not_allowed_in_url")


async def test_the_demo_holds_two_families_of_two_children(
    served: tuple[Demo, httpx.AsyncClient],
) -> None:
    demo, client = served
    accounts = (await client.get("/v1/accounts", headers=bearer(demo))).json()["items"]
    slugs: dict[str, list[str]] = {}

    for account in accounts:
        listing = await client.get(f"/v1/accounts/{account['id']}/children", headers=bearer(demo))
        slugs[account["id"]] = [child["slug"] for child in listing.json()["items"]]

    assert slugs == {"marta": ["lucia", "mateo"], "pablo": ["hugo", "alba"]}


async def test_each_account_says_in_its_label_that_the_family_is_made_up(
    served: tuple[Demo, httpx.AsyncClient],
) -> None:
    demo, client = served

    accounts = (await client.get("/v1/accounts", headers=bearer(demo))).json()["items"]

    assert [account["label"] for account in accounts] == [
        "Marta (made up)",
        "Pablo (made up)",
    ]


async def test_the_demo_keeps_all_its_state_in_the_folder_it_is_given(tmp_path: Path) -> None:
    async with running(tmp_path / "state") as (demo, _client):
        assert demo.settings.state_dir == tmp_path / "state"


async def test_the_demo_key_holds_every_scope_so_it_may_lift_a_block(
    served: tuple[Demo, httpx.AsyncClient],
) -> None:
    demo, client = served

    response = await client.post("/v1/accounts/marta/connection/reset", headers=bearer(demo))

    assert response.status_code == 200


async def test_the_documentation_is_on(served: tuple[Demo, httpx.AsyncClient]) -> None:
    _, client = served

    response = await client.get("/docs")

    assert response.status_code == 200


async def test_a_request_without_the_key_is_refused(
    served: tuple[Demo, httpx.AsyncClient],
) -> None:
    _, client = served

    response = await client.get("/v1/accounts")

    assert response.status_code == 401


async def test_the_variables_of_a_real_setup_do_not_reach_the_demo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ALEXIA_API_DOCS_ENABLED", "false")
    monkeypatch.setenv("ALEXIA_API_ALLOW_WRITES", "true")

    async with running(tmp_path / "state") as (demo, _client):
        assert demo.settings.docs_enabled is True
        assert demo.settings.allow_writes is False


async def test_nothing_is_written_outside_the_state_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    state = tmp_path / "state"

    async with running(state) as (demo, client):
        await client.get("/v1/accounts/marta/children/lucia/tracking", headers=bearer(demo))

    assert list(elsewhere.iterdir()) == []
    assert [path.name for path in state.iterdir()] == [FILE_NAME]


def test_the_state_folder_is_removed_when_the_demo_ends() -> None:
    with demo_state() as folder:
        assert folder.is_dir()

    assert not folder.exists()


def test_the_signal_that_container_runtimes_send_is_one_that_ends_the_demo_cleanly() -> None:
    assert signal.SIGTERM in ENDING_SIGNALS


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no hangup signal")
def test_closing_a_terminal_ends_the_demo_cleanly_too() -> None:
    assert signal.Signals["SIGHUP"] in ENDING_SIGNALS


@pytest.mark.parametrize("ending", ENDING_SIGNALS, ids=lambda ending: ending.name)
def test_a_signal_to_end_still_removes_the_folder_and_ends_as_a_termination_request(
    ending: signal.Signals,
) -> None:
    with pytest.raises(SystemExit) as raised, demo_state() as folder:
        signal.raise_signal(ending)

    assert raised.value.code == 128 + signal.SIGTERM
    assert not folder.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no hangup signal")
def test_a_hangup_goes_to_whatever_handles_termination_at_that_moment() -> None:
    heard: list[int] = []

    with demo_state():
        signal.signal(signal.SIGTERM, lambda signum, _frame: heard.append(signum))
        signal.raise_signal(signal.Signals["SIGHUP"])

    assert heard == [signal.SIGTERM]


def test_the_handlers_for_those_signals_are_put_back() -> None:
    before = {ending: signal.getsignal(ending) for ending in ENDING_SIGNALS}

    with demo_state():
        assert all(signal.getsignal(ending) != before[ending] for ending in ENDING_SIGNALS)

    assert {ending: signal.getsignal(ending) for ending in ENDING_SIGNALS} == before


def test_the_banner_shows_the_key_the_documentation_and_a_request_for_each_suggestion() -> None:
    text = banner("http://127.0.0.1:8000", KEY, CALENDAR_KEY)

    lines = [line.strip() for line in text.splitlines()]
    assert KEY in lines
    assert "http://127.0.0.1:8000/docs" in lines
    for item in TOUR:
        request = f'curl -H "Authorization: Bearer {KEY}" "http://127.0.0.1:8000{item.path}"'
        if item.save_as:
            request += f' --output "{item.save_as}"'
        assert lines[lines.index(f"# {item.what}") + 1] == request


def test_the_banner_gives_a_calendar_app_the_calendar_key_and_never_the_other_key() -> None:
    text = banner("http://127.0.0.1:8000", KEY, CALENDAR_KEY)

    lines = [line.strip() for line in text.splitlines()]
    assert f"http://127.0.0.1:8000{CALENDAR_PATH}?key={CALENDAR_KEY}" in lines
    assert [line for line in lines if "?key=" in line and KEY in line] == []


def test_only_a_request_that_answers_with_a_file_tells_curl_where_to_save_it() -> None:
    text = banner("http://127.0.0.1:8000", KEY, CALENDAR_KEY)

    assert text.count("--output") == 2
    assert 'museo.pdf"' in text
    assert 'familia.ics"' in text


def test_the_banner_promises_a_simulated_school_and_that_nothing_is_kept() -> None:
    text = banner("http://127.0.0.1:8000", KEY, CALENDAR_KEY)

    assert "against a simulated school. It needs no account and no password." in text
    assert "everything it changes is thrown away when you stop it." in text


def test_the_banner_uses_curl_exe_on_windows_where_curl_names_another_tool() -> None:
    text = banner("http://127.0.0.1:8000", KEY, CALENDAR_KEY, windows=True)

    assert f'    curl.exe -H "Authorization: Bearer {KEY}"' in text
    assert "    curl -H" not in text


@pytest.mark.parametrize(
    ("host", "port", "expected"),
    [
        ("127.0.0.1", 8000, "http://127.0.0.1:8000"),
        ("localhost", 9, "http://localhost:9"),
        ("0.0.0.0", 9100, "http://localhost:9100"),
        ("::", 9100, "http://localhost:9100"),
        ("::1", 8000, "http://[::1]:8000"),
    ],
)
def test_the_address_is_one_that_a_browser_can_open(host: str, port: int, expected: str) -> None:
    assert address(host, port) == expected
