"""The forms of an account."""

import asyncio
from dataclasses import replace

import pytest

from alexia_api.portal.forms import read_forms
from alexia_api.sim.world import DEMO_USER_A, DEMO_USER_B, synthetic_guid
from tests.api.support import Api, MakeApi, problem_of
from tests.harness import A_NEW_FORM, Harness

ACCOUNT = "/v1/accounts/marta"
FORMS = f"{ACCOUNT}/forms"
MESSAGES = f"{ACCOUNT}/messages"
ZOO = synthetic_guid(0x1401)
CANTEEN = synthetic_guid(0x1402)
RECEIVED = [synthetic_guid(number) for number in range(0x1001, 0x1009)]
MESSAGE_DATA = "GetDatosPaginaComunicado"
SELECT_FOLDER = "CarpetaSeleccionada"


async def ids_of(api: Api, path: str = FORMS) -> list[str]:
    return [item["id"] for item in (await api.get(path)).json()["items"]]


async def test_the_forms_come_newest_first_with_every_field(api: Api) -> None:
    response = await api.get(FORMS)

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": ZOO,
                "subject": "Autorización para la salida al zoo",
                "sender": "Secretaría",
                "received_on": "2026-10-16",
                "expires_on": "2026-10-30",
                "category": "Autorizaciones",
            },
            {
                "id": CANTEEN,
                "subject": "Encuesta del comedor escolar",
                "sender": "Dirección",
                "received_on": "2026-10-01",
                "expires_on": "2026-10-20",
                "category": "Encuestas",
            },
        ],
        "truncated": False,
    }


async def test_each_account_lists_only_the_forms_it_was_sent(api: Api) -> None:
    pablo = await api.get("/v1/accounts/pablo/forms")

    assert (pablo.status_code, pablo.json()) == (200, {"items": [], "truncated": False})


async def test_the_forms_are_in_no_folder_and_the_messages_hold_no_form(api: Api) -> None:
    forms = await ids_of(api)
    messages = await ids_of(api, MESSAGES)
    folders = (await api.get(f"{ACCOUNT}/folders")).json()["items"]

    assert (forms, messages) == ([ZOO, CANTEEN], RECEIVED)
    assert [(item["name"], item["count"]) for item in folders] == [("received", 8), ("sent", 2)]


async def test_a_form_is_no_message_and_a_message_is_no_form(api: Api) -> None:
    problem_of(await api.get(f"{FORMS}/{RECEIVED[0]}"), status=404, code="form_not_found")
    problem_of(await api.get(f"{MESSAGES}/{ZOO}"), status=404, code="message_not_found")

    assert api.harness.requests_to(MESSAGE_DATA) == 0


async def test_the_forms_are_stored_and_fresh_asks_the_portal_again(api: Api) -> None:
    first = await api.get(FORMS)
    reads = api.portal_calls()
    api.harness.clock.advance(60)
    second = await api.get(FORMS)
    stored = api.portal_calls()
    again = await api.get(f"{FORMS}?fresh=true")

    assert [response.headers["x-cache"] for response in (first, second, again)] == [
        "miss",
        "hit",
        "bypass",
    ]
    assert second.headers["age"] == "60"
    assert second.json() == first.json()
    assert stored == reads
    assert api.portal_calls() > stored


async def test_the_forms_are_stored_for_five_minutes(api: Api) -> None:
    first = await api.get(FORMS)
    api.harness.clock.advance(299)
    second = await api.get(FORMS)
    api.harness.clock.advance(2)
    third = await api.get(FORMS)

    assert [response.headers["x-cache"] for response in (first, second, third)] == [
        "miss",
        "hit",
        "miss",
    ]


async def test_the_time_to_store_forms_is_a_setting(make_api: MakeApi) -> None:
    api = await make_api(cache={"forms": 0})

    await api.get(FORMS)

    assert (await api.get(FORMS)).headers["x-cache"] == "miss"


async def test_a_form_that_arrived_shows_after_a_fresh_read(api: Api) -> None:
    await api.get(FORMS)
    api.harness.deliver(DEMO_USER_A, A_NEW_FORM)

    stale = await ids_of(api)
    fresh = await api.get(f"{FORMS}?fresh=true")

    assert stale == [ZOO, CANTEEN]
    assert fresh.headers["x-cache"] == "bypass"
    assert [item["id"] for item in fresh.json()["items"]] == [A_NEW_FORM.guid, ZOO, CANTEEN]


async def test_a_list_longer_than_the_server_reads_says_so(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "alexia_api.services.registry.read_forms",
        lambda tx: read_forms(tx, page_size=1, max_pages=1),
    )

    body = (await api.get(FORMS)).json()

    assert body["truncated"] is True
    assert [item["id"] for item in body["items"]] == [ZOO]


async def test_many_requests_at_once_share_one_read_of_the_forms(api: Api) -> None:
    await api.post(f"{ACCOUNT}/connection/check")

    responses = await asyncio.gather(*(api.get(FORMS) for _ in range(8)))

    assert {response.status_code for response in responses} == {200}
    assert api.harness.requests_to(SELECT_FOLDER) == 2


async def test_forms_and_messages_read_at_the_same_moment_never_get_each_others_rows(
    api: Api,
) -> None:
    paths = (FORMS, MESSAGES) * 4

    answers = await asyncio.gather(*(api.get(f"{path}?fresh=true") for path in paths))

    for path, answer in zip(paths, answers, strict=True):
        ids = [item["id"] for item in answer.json()["items"]]
        assert ids == ([ZOO, CANTEEN] if path == FORMS else RECEIVED), path


async def test_a_form_has_its_row_then_its_time_and_its_words(api: Api) -> None:
    response = await api.get(f"{FORMS}/{ZOO}")

    assert response.status_code == 200
    body = response.json()
    assert list(body) == [
        "id",
        "subject",
        "sender",
        "received_on",
        "expires_on",
        "category",
        "sent_at",
        "body",
        "links",
        "child_names",
    ]
    assert body["sent_at"] == "2026-10-16T10:00:00+02:00"
    assert body["body"]["text"] == (
        "La clase de Lucía irá al zoo el 5 de noviembre.\n\n"
        "Necesitamos su autorización antes del 30 de octubre."
    )
    assert body["body"]["simplified"] is False
    assert (body["links"], body["child_names"]) == ([], "Lucía")


async def test_the_row_of_a_form_is_what_the_list_shows_for_it(api: Api) -> None:
    listed = {item["id"]: item for item in (await api.get(FORMS)).json()["items"]}

    body = (await api.get(f"{FORMS}/{CANTEEN}")).json()

    assert {key: body[key] for key in listed[CANTEEN]} == listed[CANTEEN]
    assert body["child_names"] == "Lucía, Mateo"


async def test_a_form_is_found_by_its_id_in_any_letter_case(api: Api) -> None:
    body = (await api.get(f"{FORMS}/{ZOO.upper()}")).json()

    assert body["id"] == ZOO


@pytest.mark.parametrize(
    "reference", ["not-an-id", "5afe0000-0000-4000-8000-00000000140", f"{ZOO}0"]
)
async def test_what_is_no_form_id_is_not_found_without_asking_the_portal(
    api: Api, reference: str
) -> None:
    body = problem_of(await api.get(f"{FORMS}/{reference}"), status=404, code="form_not_found")

    assert "fresh=true" in body["detail"]
    assert api.portal_calls() == 0


async def test_a_form_the_list_does_not_hold_is_not_found_and_never_opened(api: Api) -> None:
    unknown = synthetic_guid(0x9999)

    problem_of(await api.get(f"{FORMS}/{unknown}"), status=404, code="form_not_found")

    assert api.harness.requests_to("Comunicado.aspx") == 0
    assert api.harness.requests_to(MESSAGE_DATA) == 0


async def test_a_long_form_reference_is_cut_before_it_is_echoed(api: Api) -> None:
    response = await api.get(f"{FORMS}/{'x' * 200}")

    body = problem_of(response, status=404, code="form_not_found")
    assert "x" * 80 + "..." in body["detail"]
    assert "x" * 81 not in body["detail"]


async def test_the_form_of_another_account_is_not_found(api: Api) -> None:
    theirs = replace(A_NEW_FORM, guid=synthetic_guid(0x1411))
    api.harness.deliver(DEMO_USER_B, theirs)

    assert (await api.get(f"/v1/accounts/pablo/forms/{theirs.guid}")).status_code == 200
    problem_of(await api.get(f"{FORMS}/{theirs.guid}"), status=404, code="form_not_found")


async def test_a_form_that_arrived_since_is_found_only_after_a_fresh_read(api: Api) -> None:
    await api.get(FORMS)
    api.harness.deliver(DEMO_USER_A, A_NEW_FORM)

    problem_of(await api.get(f"{FORMS}/{A_NEW_FORM.guid}"), status=404, code="form_not_found")
    found = await api.get(f"{FORMS}/{A_NEW_FORM.guid}?fresh=true")

    assert found.status_code == 200
    assert found.json()["subject"] == "Autorización para la visita al huerto"


async def test_a_form_is_stored_after_it_is_read(api: Api) -> None:
    first = await api.get(f"{FORMS}/{ZOO}")
    api.harness.clock.advance(60)
    second = await api.get(f"{FORMS}/{ZOO}")
    again = await api.get(f"{FORMS}/{ZOO}?fresh=true")

    assert [response.headers["x-cache"] for response in (first, second, again)] == [
        "miss",
        "hit",
        "bypass",
    ]
    assert second.headers["age"] == "60"
    assert api.harness.requests_to(MESSAGE_DATA) == 2


async def test_the_time_a_form_was_sent_has_the_offset_of_the_school_zone(
    make_api: MakeApi,
) -> None:
    api = await make_api(timezone="Asia/Tokyo")

    body = (await api.get(f"{FORMS}/{ZOO}")).json()

    assert body["sent_at"] == "2026-10-16T10:00:00+09:00"


@pytest.mark.parametrize("path", [FORMS, f"{FORMS}/{ZOO}"])
async def test_a_form_asked_for_in_a_way_that_makes_no_sense_is_a_validation_error(
    api: Api, path: str
) -> None:
    problem_of(await api.get(f"{path}?fresh=maybe"), status=422, code="validation_error")

    assert api.portal_calls() == 0


async def test_the_words_of_a_hostile_form_reach_the_client_clean(api: Api) -> None:
    hostile = replace(
        A_NEW_FORM,
        guid=synthetic_guid(0x1404),
        body_html=(
            '<script>alert(1)</script><p onclick="steal()">hola</p>'
            '<a href="javascript:alert(1)">pulse</a>'
        ),
    )
    api.harness.deliver(DEMO_USER_A, hostile)

    body = (await api.get(f"{FORMS}/{hostile.guid}?fresh=true")).json()["body"]

    for banned in ("<script", "onclick", "javascript:"):
        assert banned not in body["html"]
    assert body["text"] == "hola\n\npulse"


async def test_a_list_that_changed_shape_is_a_bad_gateway_and_leaves_the_messages_alone(
    api: Api,
) -> None:
    api.harness.sim.options.feed_cell_count = 12

    body = problem_of(await api.get(FORMS), status=502, code="portal_changed")
    api.harness.sim.options.feed_cell_count = None
    messages = await ids_of(api, f"{MESSAGES}?fresh=true")
    forms = await ids_of(api, f"{FORMS}?fresh=true")

    assert "cells instead of 11" in body["detail"]
    assert (messages, forms) == (RECEIVED, [ZOO, CANTEEN])
    assert api.harness.sim.counters.login_attempts == 2


async def test_a_portal_that_ignores_the_address_is_a_bad_gateway_and_not_a_list_of_messages(
    api: Api,
) -> None:
    api.harness.sim.options.forms_page_ignores_query = True

    body = problem_of(await api.get(FORMS), status=502, code="unexpected_reply")

    assert "does not say that it lists forms" in body["detail"]
    assert api.harness.requests_to(SELECT_FOLDER) == 0


async def test_a_failed_read_is_not_stored(api: Api) -> None:
    api.harness.sim.options.feed_cell_count = 12
    problem_of(await api.get(FORMS), status=502, code="portal_changed")
    api.harness.sim.options.feed_cell_count = None

    again = await api.get(FORMS)

    assert (again.status_code, again.headers["x-cache"]) == (200, "miss")


async def test_a_session_the_portal_dropped_is_replaced_without_the_client_noticing(
    api: Api,
) -> None:
    await api.get(FORMS)
    api.harness.sim.expire_all_sessions()

    response = await api.get(f"{FORMS}?fresh=true")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [ZOO, CANTEEN]
    assert api.harness.sim.counters.login_attempts == 2


@pytest.mark.parametrize("path", [FORMS, f"{FORMS}/{ZOO}"])
async def test_every_forms_route_says_503_for_a_blocked_account(
    make_api: MakeApi, harness: Harness, path: str
) -> None:
    api = await make_api(accounts={"marta": harness.account_settings(password="not-the-password")})
    await api.post(f"{ACCOUNT}/connection/check")

    problem_of(await api.get(path), status=503, code="breaker_open")

    assert api.harness.sim.counters.login_attempts == 1
