"""The simulator's forms, and the checks that keep it as strict as the portal is believed to be.

The reader of forms only means something if the simulator refuses what the portal would refuse.
These tests switch the list in the wrong order or the wrong way, one detail at a time, and they
pin down which list a session shows and which folder counts a form.
"""

import pytest

from alexia_api.domain.errors import UnexpectedReply, WsRejected
from alexia_api.domain.messages import FolderName
from alexia_api.portal import wire
from alexia_api.portal.allowlist import SELECT_FOLDER
from alexia_api.portal.folders import FOLDER_IDS, read_folder_tree, select_folder
from alexia_api.portal.forms import enter_forms, leave_forms
from alexia_api.portal.inbox import read_feed, read_pages
from alexia_api.portal.pages import COMUNICADOS_PAGE, PAGE_ACCEPT, PageRequest, get_page
from alexia_api.portal.session import Tx
from alexia_api.portal.ws import call_ws
from alexia_api.sim.world import synthetic_guid
from tests.harness import Failure, Harness

FORM_IDS = [synthetic_guid(0x1401), synthetic_guid(0x1402)]
RECEIVED_IDS = [synthetic_guid(0x1001 + index) for index in range(8)]


async def ids_of_the_list(tx: Tx) -> list[str]:
    return [row.id for row in (await read_pages(tx)).messages]


async def load_the_message_page(tx: Tx, query: str) -> None:
    await get_page(
        tx,
        PageRequest(
            name="test page",
            path=f"{COMUNICADOS_PAGE}{query}",
            referer=tx.absolute(COMUNICADOS_PAGE),
            accept=PAGE_ACCEPT,
        ),
    )


async def test_the_list_follows_the_page_that_was_loaded_last(harness: Harness) -> None:
    async def recipe(tx: Tx) -> list[list[str]]:
        before = await ids_of_the_list(tx)
        await enter_forms(tx)
        in_forms = await ids_of_the_list(tx)
        await leave_forms(tx)
        return [before, in_forms, await ids_of_the_list(tx)]

    before, in_forms, after = await harness.gateway().call(recipe)

    assert before == after == RECEIVED_IDS
    assert in_forms == FORM_IDS


@pytest.mark.parametrize("folder", ["received", "sent"])
async def test_a_form_is_in_no_folder(harness: Harness, folder: FolderName) -> None:
    feed = await harness.gateway().call(lambda tx: read_feed(tx, folder))

    assert not set(FORM_IDS) & {row.id for row in feed.messages}


async def test_a_form_is_in_no_count_of_the_folders(harness: Harness) -> None:
    folders = await harness.gateway().call(read_folder_tree)

    assert {folder.name: folder.count for folder in folders} == {"received": 8, "sent": 2}


@pytest.mark.parametrize(
    "query", ["?autorizaciones=0", "?autorizaciones=1&other=1", "?other=1", "?autorizaciones="]
)
async def test_a_message_page_asked_in_another_way_is_a_server_error(
    harness: Harness, failure: Failure, query: str
) -> None:
    detail = await failure(harness.gateway().call(lambda tx: load_the_message_page(tx, query)))

    assert detail == UnexpectedReply(where="page:test page HTTP 500")


async def test_choosing_a_folder_for_the_forms_before_the_page_is_a_server_fault(
    harness: Harness, failure: Failure
) -> None:
    async def recipe(tx: Tx) -> object:
        params = wire.SelectFolderParams(folder_id=FOLDER_IDS["received"], is_authorization="1")
        return await call_ws(tx, SELECT_FOLDER, params)

    detail = await failure(harness.gateway().call(recipe))

    assert isinstance(detail, WsRejected)


async def test_choosing_a_folder_for_messages_while_the_page_is_on_the_forms_is_a_fault(
    harness: Harness, failure: Failure
) -> None:
    async def recipe(tx: Tx) -> None:
        await load_the_message_page(tx, "?autorizaciones=1")
        await select_folder(tx, "received")

    detail = await failure(harness.gateway().call(recipe))

    assert isinstance(detail, WsRejected)


async def test_a_new_session_starts_on_the_messages(harness: Harness) -> None:
    gateway = harness.gateway()

    async def stay_in_the_forms(tx: Tx) -> None:
        await enter_forms(tx)

    await gateway.call(stay_in_the_forms)
    other = harness.gateway(account="other")

    assert await other.call(ids_of_the_list) == RECEIVED_IDS
