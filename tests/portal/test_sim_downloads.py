"""The simulator refuses a file request that the real portal would refuse.

The reader tests only mean something if the simulator is as strict as the portal. These tests send
the request wrong, one detail at a time, and expect the portal's error page.
"""

from collections.abc import Callable

import httpx
import pytest

from alexia_api.portal.attachments import attachment_path
from alexia_api.portal.message import message_path, open_message
from alexia_api.portal.session import PortalRequest, PortalResponse, Tx
from alexia_api.sim.app import LOGON_PATH
from alexia_api.sim.world import synthetic_guid
from tests.harness import Harness, listed_row, seeded

MESSAGE = 0x1002
ANOTHER_MESSAGE = 0x1006

BROKEN: dict[str, Callable[[str], str]] = {
    "another kind of file": lambda path: path.replace("tipo=6", "tipo=5"),
    "an extra field": lambda path: f"{path}&extra=1",
    "a name that is not the file's": lambda path: path.replace("&alias=", "&alias=x"),
    "no file id": lambda path: path.replace("&nombre=", "&nom="),
}


async def request_file(
    harness: Harness,
    *,
    change: Callable[[str], str] = lambda path: path,
    accept: str = "*/*",
    referer_is_the_message: bool = True,
    open_first: int | None = MESSAGE,
) -> PortalResponse:
    (file,) = seeded(MESSAGE).files
    gateway = harness.gateway()
    row = await listed_row(gateway, MESSAGE)
    opened = await listed_row(gateway, open_first) if open_first is not None else None

    async def ask(tx: Tx) -> PortalResponse:
        if opened is not None:
            await open_message(tx, opened.id)
        return await tx.request(
            PortalRequest(
                method="GET",
                path=change(attachment_path(file.id, file.name)),
                headers={"accept": accept},
                referer=tx.absolute(message_path(row.id) if referer_is_the_message else "/"),
                follow=False,
            )
        )

    return await gateway.call(ask)


async def test_a_request_shaped_like_the_portals_own_gets_the_file_as_a_plain_stream(
    harness: Harness,
) -> None:
    (file,) = seeded(MESSAGE).files

    response = await request_file(harness)

    assert response.status == 200
    assert response.body == file.data
    assert response.headers["content-type"] == "application/octet-stream"


@pytest.mark.parametrize("how", sorted(BROKEN))
async def test_a_request_that_is_shaped_wrong_gets_the_error_page(
    harness: Harness, how: str
) -> None:
    response = await request_file(harness, change=BROKEN[how])

    assert response.status == 500
    assert b"Error" in response.body


async def test_a_file_asked_for_before_its_message_is_opened_gets_the_error_page(
    harness: Harness,
) -> None:
    assert (await request_file(harness, open_first=None)).status == 500


async def test_a_file_of_another_message_than_the_open_one_gets_the_error_page(
    harness: Harness,
) -> None:
    assert (await request_file(harness, open_first=ANOTHER_MESSAGE)).status == 500


async def test_a_request_that_does_not_accept_any_type_gets_the_error_page(
    harness: Harness,
) -> None:
    assert (await request_file(harness, accept="text/html")).status == 500


async def test_a_request_that_does_not_come_from_the_message_page_gets_the_error_page(
    harness: Harness,
) -> None:
    assert (await request_file(harness, referer_is_the_message=False)).status == 500


async def test_the_referer_check_can_be_switched_off(harness: Harness) -> None:
    harness.sim.options.require_referer = False

    assert (await request_file(harness, referer_is_the_message=False)).status == 200


async def test_without_a_session_the_visitor_is_sent_to_the_logon_page(harness: Harness) -> None:
    (file,) = seeded(MESSAGE).files

    async with httpx.AsyncClient(
        transport=harness.sim.transport(), base_url=harness.sim.base_url
    ) as client:
        response = await client.get(attachment_path(file.id, file.name), headers={"accept": "*/*"})

    assert response.status_code == 302
    assert response.headers["location"].startswith(LOGON_PATH)
    assert harness.sim.counters.downloads == 0
    assert synthetic_guid(MESSAGE) not in response.headers["location"]
