"""The message folders and message lists of an account."""

import asyncio
from dataclasses import replace

import pytest

from alexia_api.portal.inbox import read_feed
from alexia_api.sim.world import DEMO_USER_A, synthetic_guid
from tests.api.support import Api, MakeApi, problem_of
from tests.harness import A_NEW_MESSAGE, Harness

ACCOUNT = "/v1/accounts/marta"
FOLDERS = f"{ACCOUNT}/folders"
MESSAGES = f"{ACCOUNT}/messages"
RECEIVED = [synthetic_guid(number) for number in range(0x1001, 0x1009)]
UNREAD = [synthetic_guid(0x1001), synthetic_guid(0x1003)]


async def ids_of(api: Api, query: str = "") -> list[str]:
    body = (await api.get(f"{MESSAGES}?{query}")).json()
    return [item["id"] for item in body["items"]]


async def test_the_folders_of_the_mailbox(api: Api) -> None:
    response = await api.get(FOLDERS)

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"name": "received", "label": "Recibidos", "count": 8},
            {"name": "sent", "label": "Enviados", "count": 2},
        ]
    }


async def test_each_account_lists_the_folders_of_its_own_mailbox(api: Api) -> None:
    pablo = (await api.get("/v1/accounts/pablo/folders")).json()["items"]

    assert [(item["name"], item["count"]) for item in pablo] == [("received", 3), ("sent", 1)]


async def test_the_folders_are_stored_and_fresh_asks_the_portal_again(api: Api) -> None:
    first = await api.get(FOLDERS)
    api.harness.clock.advance(60)
    second = await api.get(FOLDERS)
    again = await api.get(f"{FOLDERS}?fresh=true")

    assert [response.headers["x-cache"] for response in (first, second, again)] == [
        "miss",
        "hit",
        "bypass",
    ]
    assert second.headers["age"] == "60"
    assert api.harness.requests_to("GetArbolCarpetasJSON") == 2


async def test_the_messages_come_newest_first(api: Api) -> None:
    body = (await api.get(MESSAGES)).json()

    assert [item["id"] for item in body["items"]] == RECEIVED
    assert body["total"] == 8
    assert (body["limit"], body["offset"], body["next_offset"]) == (25, 0, None)
    assert body["truncated"] is False


async def test_a_message_shows_what_the_portal_lists_about_it(api: Api) -> None:
    items = (await api.get(MESSAGES)).json()["items"]

    assert items[0] == {
        "id": synthetic_guid(0x1001),
        "read": False,
        "institutional": False,
        "sender": "Ana Muestra Tutora",
        "subject": "Reto de matemáticas",
        "received_on": "2026-10-15",
        "expires_on": None,
        "anonymous": False,
        "category": "Aviso",
        "has_attachments": False,
    }
    assert items[1]["subject"] == "Excursión al museo"
    assert (items[1]["read"], items[1]["expires_on"]) == (True, "2026-10-25")


async def test_the_flags_and_the_sender_of_a_message_come_through(api: Api) -> None:
    items = {item["id"]: item for item in (await api.get(MESSAGES)).json()["items"]}

    assert items[synthetic_guid(0x1006)]["anonymous"] is True
    assert items[synthetic_guid(0x1005)]["institutional"] is True
    assert items[synthetic_guid(0x1008)]["sender"] == "Dirección & Secretaría"


async def test_each_account_lists_only_its_own_messages(api: Api) -> None:
    pablo = (await api.get("/v1/accounts/pablo/messages")).json()

    assert pablo["total"] == 3
    assert {item["id"] for item in pablo["items"]}.isdisjoint(RECEIVED)


async def test_the_sent_folder_lists_what_the_family_sent(api: Api) -> None:
    body = (await api.get(f"{MESSAGES}?folder=sent")).json()

    assert [item["subject"] for item in body["items"]] == [
        "Ausencia de Lucía",
        "Consulta sobre la excursión",
    ]


@pytest.mark.parametrize("query", ["folder=drafts", "folder="])
async def test_a_folder_this_server_does_not_serve_is_a_validation_error(
    api: Api, query: str
) -> None:
    problem_of(await api.get(f"{MESSAGES}?{query}"), status=422, code="validation_error")

    assert api.portal_calls() == 0


async def test_paging_walks_the_folder_and_reads_the_portal_once(api: Api) -> None:
    pages = []
    offset: int | None = 0
    while offset is not None:
        page = (await api.get(f"{MESSAGES}?limit=3&offset={offset}")).json()
        pages.append(page)
        offset = page["next_offset"]

    assert [len(page["items"]) for page in pages] == [3, 3, 2]
    assert [page["next_offset"] for page in pages] == [3, 6, None]
    assert {page["total"] for page in pages} == {8}
    assert [item["id"] for page in pages for item in page["items"]] == RECEIVED
    assert api.harness.requests_to("Comunicados.aspx") == 1


@pytest.mark.parametrize(("limit", "next_offset"), [(7, 7), (8, None), (9, None)])
async def test_the_next_page_is_named_only_when_there_is_one(
    api: Api, limit: int, next_offset: int | None
) -> None:
    body = (await api.get(f"{MESSAGES}?limit={limit}")).json()

    assert body["next_offset"] == next_offset


async def test_an_offset_past_the_end_is_an_empty_last_page(api: Api) -> None:
    body = (await api.get(f"{MESSAGES}?offset=50")).json()

    assert (body["items"], body["total"], body["offset"], body["next_offset"]) == ([], 8, 50, None)


async def test_unread_keeps_the_messages_that_are_not_known_to_be_read(api: Api) -> None:
    unread = (await api.get(f"{MESSAGES}?unread=true")).json()

    assert [item["id"] for item in unread["items"]] == UNREAD
    assert (unread["total"], unread["next_offset"]) == (2, None)


async def test_unread_false_keeps_the_messages_that_were_read(api: Api) -> None:
    read = (await api.get(f"{MESSAGES}?unread=false")).json()

    assert read["total"] == 6
    assert [item["id"] for item in read["items"]] == [id_ for id_ in RECEIVED if id_ not in UNREAD]


async def test_a_message_with_an_icon_nobody_knows_counts_as_not_known_to_be_read(
    api: Api,
) -> None:
    unknown = synthetic_guid(0x1200)
    api.harness.deliver(DEMO_USER_A, replace(A_NEW_MESSAGE, guid=unknown, read=None))

    everything = (await api.get(MESSAGES)).json()["items"]

    assert (everything[0]["id"], everything[0]["read"]) == (unknown, None)
    assert await ids_of(api, "unread=true") == [unknown, *UNREAD]
    assert unknown not in await ids_of(api, "unread=false")


async def test_paging_applies_after_the_filter(api: Api) -> None:
    first = (await api.get(f"{MESSAGES}?unread=true&limit=1")).json()
    second = (await api.get(f"{MESSAGES}?unread=true&limit=1&offset=1")).json()

    assert (first["total"], first["next_offset"], second["next_offset"]) == (2, 1, None)
    assert [item["id"] for item in first["items"] + second["items"]] == UNREAD


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=101", "limit=-1", "limit=many", "offset=-1", "offset=1.5", "unread=maybe"],
)
async def test_a_page_that_makes_no_sense_is_a_validation_error(api: Api, query: str) -> None:
    problem_of(await api.get(f"{MESSAGES}?{query}"), status=422, code="validation_error")

    assert api.portal_calls() == 0


@pytest.mark.parametrize("limit", [1, 100])
async def test_the_page_size_may_be_anything_from_one_to_one_hundred(api: Api, limit: int) -> None:
    body = (await api.get(f"{MESSAGES}?limit={limit}")).json()

    assert (body["limit"], len(body["items"])) == (limit, min(limit, 8))


async def test_the_messages_are_stored_and_expire_after_two_minutes(api: Api) -> None:
    first = await api.get(MESSAGES)
    api.harness.clock.advance(119)
    second = await api.get(MESSAGES)
    api.harness.clock.advance(2)
    third = await api.get(MESSAGES)

    assert [response.headers["x-cache"] for response in (first, second, third)] == [
        "miss",
        "hit",
        "miss",
    ]
    assert second.headers["age"] == "119"


async def test_a_message_that_arrived_shows_after_a_fresh_read(api: Api) -> None:
    await api.get(MESSAGES)
    api.harness.deliver(DEMO_USER_A, A_NEW_MESSAGE)

    stale = await ids_of(api)
    fresh = await api.get(f"{MESSAGES}?fresh=true")

    assert stale == RECEIVED
    assert fresh.headers["x-cache"] == "bypass"
    assert [item["id"] for item in fresh.json()["items"]] == [A_NEW_MESSAGE.guid, *RECEIVED]


async def test_a_folder_longer_than_the_server_reads_says_so(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "alexia_api.services.registry.read_feed",
        lambda tx, folder: read_feed(tx, folder, page_size=3, max_pages=1),
    )

    body = (await api.get(MESSAGES)).json()

    assert body["truncated"] is True
    assert (body["total"], [item["id"] for item in body["items"]]) == (3, RECEIVED[:3])


async def test_many_requests_at_once_share_one_read_of_the_folder(api: Api) -> None:
    await api.post(f"{ACCOUNT}/connection/check")

    responses = await asyncio.gather(*(api.get(MESSAGES) for _ in range(8)))

    assert {response.status_code for response in responses} == {200}
    assert api.harness.requests_to("Comunicados.aspx") == 1


@pytest.mark.parametrize("path", [FOLDERS, MESSAGES])
async def test_every_mailbox_route_says_503_for_a_blocked_account(
    make_api: MakeApi, harness: Harness, path: str
) -> None:
    api = await make_api(accounts={"marta": harness.account_settings(password="not-the-password")})
    await api.post(f"{ACCOUNT}/connection/check")

    problem_of(await api.get(path), status=503, code="breaker_open")

    assert api.harness.sim.counters.login_attempts == 1
