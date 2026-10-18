"""The message folders and message lists of an account."""

import asyncio
from dataclasses import replace

import pytest

from alexia_api.config import CacheTtls
from alexia_api.domain.ids import attachment_token
from alexia_api.portal.inbox import read_feed
from alexia_api.sim.world import DEMO_USER_A, synthetic_guid
from tests.api.support import Api, MakeApi, problem_of
from tests.harness import A_NEW_MESSAGE, Harness, seeded

ACCOUNT = "/v1/accounts/marta"
FOLDERS = f"{ACCOUNT}/folders"
MESSAGES = f"{ACCOUNT}/messages"
RECEIVED = [synthetic_guid(number) for number in range(0x1001, 0x1009)]
UNREAD = [synthetic_guid(0x1001), synthetic_guid(0x1003)]
WITH_FILE = synthetic_guid(0x1002)
MESSAGE_DATA = "GetDatosPaginaComunicado"


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


async def test_a_message_has_its_row_then_its_time_its_words_its_links_and_its_files(
    api: Api,
) -> None:
    response = await api.get(f"{MESSAGES}/{WITH_FILE}")

    assert response.status_code == 200
    body = response.json()
    (file,) = seeded(0x1002).files
    assert list(body) == [
        "id",
        "read",
        "institutional",
        "sender",
        "subject",
        "received_on",
        "expires_on",
        "anonymous",
        "category",
        "has_attachments",
        "sent_at",
        "body",
        "links",
        "attachments",
        "translations",
        "child_names",
        "can_reply",
    ]
    assert body["sent_at"] == "2026-10-14T17:40:00+02:00"
    assert body["body"]["text"] == (
        "Adjuntamos la autorización para la excursión al museo.\n\n"
        "Por favor, responda a la encuesta antes del 25 de octubre en este formulario "
        "(https://forms.office.com/r/ejemplo)."
    )
    assert body["body"]["simplified"] is False
    assert body["links"] == [
        {"url": "https://forms.office.com/r/ejemplo", "host": "forms.office.com", "kind": "form"}
    ]
    assert body["attachments"] == [
        {
            "id": attachment_token(file.id),
            "name": "Autorización museo.pdf",
            "size": len(file.data),
        }
    ]
    assert body["translations"] == []
    assert (body["child_names"], body["can_reply"]) == ("Lucía, Mateo", False)


async def test_the_row_of_a_message_is_what_the_list_shows_for_it(api: Api) -> None:
    listed = {item["id"]: item for item in (await api.get(MESSAGES)).json()["items"]}

    body = (await api.get(f"{MESSAGES}/{WITH_FILE}")).json()

    assert {key: body[key] for key in listed[WITH_FILE]} == listed[WITH_FILE]


async def test_a_message_is_found_by_its_id_in_any_letter_case(api: Api) -> None:
    body = (await api.get(f"{MESSAGES}/{WITH_FILE.upper()}")).json()

    assert body["id"] == WITH_FILE


async def test_a_message_the_family_sent_needs_the_sent_folder(api: Api) -> None:
    sent = synthetic_guid(0x2001)

    found = await api.get(f"{MESSAGES}/{sent}?folder=sent")

    assert found.status_code == 200
    assert found.json()["subject"] == "Ausencia de Lucía"
    problem_of(await api.get(f"{MESSAGES}/{sent}"), status=404, code="message_not_found")


@pytest.mark.parametrize(
    "reference", ["not-an-id", "5afe0000-0000-4000-8000-00000000100", f"{RECEIVED[0]}0"]
)
async def test_what_is_no_message_id_is_not_found_without_asking_the_portal(
    api: Api, reference: str
) -> None:
    body = problem_of(
        await api.get(f"{MESSAGES}/{reference}"), status=404, code="message_not_found"
    )

    assert "fresh=true" in body["detail"]
    assert api.portal_calls() == 0


async def test_a_message_the_list_does_not_hold_is_not_found_and_never_opened(api: Api) -> None:
    unknown = synthetic_guid(0x9999)

    problem_of(await api.get(f"{MESSAGES}/{unknown}"), status=404, code="message_not_found")

    assert api.harness.requests_to("Comunicado.aspx") == 0
    assert api.harness.requests_to(MESSAGE_DATA) == 0


async def test_a_long_message_reference_is_cut_before_it_is_echoed(api: Api) -> None:
    response = await api.get(f"{MESSAGES}/{'x' * 200}")

    body = problem_of(response, status=404, code="message_not_found")
    assert "x" * 80 + "..." in body["detail"]
    assert "x" * 81 not in body["detail"]


async def test_the_message_of_another_account_is_not_found(api: Api) -> None:
    theirs = synthetic_guid(0x1101)

    assert (await api.get(f"/v1/accounts/pablo/messages/{theirs}")).status_code == 200
    problem_of(await api.get(f"{MESSAGES}/{theirs}"), status=404, code="message_not_found")


async def test_a_message_is_stored_after_it_is_read(api: Api) -> None:
    first = await api.get(f"{MESSAGES}/{RECEIVED[0]}")
    api.harness.clock.advance(60)
    second = await api.get(f"{MESSAGES}/{RECEIVED[0]}")
    again = await api.get(f"{MESSAGES}/{RECEIVED[0]}?fresh=true")

    assert [response.headers["x-cache"] for response in (first, second, again)] == [
        "miss",
        "hit",
        "bypass",
    ]
    assert second.headers["age"] == "60"
    assert api.harness.requests_to(MESSAGE_DATA) == 2


async def test_the_words_of_a_message_are_stored_for_fifteen_minutes(make_api: MakeApi) -> None:
    api = await make_api(cache=CacheTtls(messages=100_000))
    path = f"{MESSAGES}/{RECEIVED[0]}"

    first = await api.get(path)
    api.harness.clock.advance(899)
    second = await api.get(path)
    api.harness.clock.advance(2)
    third = await api.get(path)

    assert [response.headers["x-cache"] for response in (first, second, third)] == [
        "miss",
        "hit",
        "miss",
    ]


async def test_the_time_a_message_was_sent_has_the_offset_of_the_school_zone(
    make_api: MakeApi,
) -> None:
    api = await make_api(timezone="Asia/Tokyo")

    body = (await api.get(f"{MESSAGES}/{WITH_FILE}")).json()

    assert body["sent_at"] == "2026-10-14T17:40:00+09:00"


@pytest.mark.parametrize("query", ["folder=drafts", "folder=", "fresh=maybe"])
async def test_a_message_asked_for_in_a_way_that_makes_no_sense_is_a_validation_error(
    api: Api, query: str
) -> None:
    problem_of(
        await api.get(f"{MESSAGES}/{RECEIVED[0]}?{query}"), status=422, code="validation_error"
    )

    assert api.portal_calls() == 0


async def test_the_words_of_a_hostile_message_reach_the_client_clean(api: Api) -> None:
    hostile = replace(
        A_NEW_MESSAGE,
        guid=synthetic_guid(0x1300),
        body_html=(
            '<script>alert(1)</script><p onclick="steal()">hola</p>'
            '<a href="javascript:alert(1)">pulse</a>'
        ),
    )
    api.harness.deliver(DEMO_USER_A, hostile)

    body = (await api.get(f"{MESSAGES}/{hostile.guid}?fresh=true")).json()["body"]

    for banned in ("<script", "onclick", "javascript:"):
        assert banned not in body["html"]
    assert body["text"] == "hola\n\npulse"


async def test_a_page_that_changed_shape_is_a_bad_gateway_that_does_not_leak_the_reply(
    api: Api,
) -> None:
    api.harness.sim.options.message_time = "25:99"

    response = await api.get(f"{MESSAGES}/{RECEIVED[0]}")

    body = problem_of(response, status=502, code="portal_changed")
    assert "25:99" not in response.text
    assert body["request_id"]


@pytest.mark.parametrize("path", [FOLDERS, MESSAGES, f"{MESSAGES}/{RECEIVED[0]}"])
async def test_every_mailbox_route_says_503_for_a_blocked_account(
    make_api: MakeApi, harness: Harness, path: str
) -> None:
    api = await make_api(accounts={"marta": harness.account_settings(password="not-the-password")})
    await api.post(f"{ACCOUNT}/connection/check")

    problem_of(await api.get(path), status=503, code="breaker_open")

    assert api.harness.sim.counters.login_attempts == 1
