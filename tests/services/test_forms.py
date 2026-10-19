"""The forms of an account, as the registry reads, keeps, and serves them."""

import asyncio
from datetime import date

import pytest

from alexia_api.clock import ManualClock
from alexia_api.config import CacheTtls
from alexia_api.domain.forms import FormSummary
from alexia_api.services.errors import NotFoundError
from alexia_api.sim.world import DEMO_USER_A, DEMO_USER_B, synthetic_guid
from tests.harness import A_NEW_FORM, Harness

ZOO = synthetic_guid(0x1401)
CANTEEN = synthetic_guid(0x1402)
UNREAD = synthetic_guid(0x1001)
MESSAGE_DATA = "GetDatosPaginaComunicado"


async def test_the_forms_of_an_account_come_newest_first(harness: Harness) -> None:
    runtime = harness.registry().get("marta")

    listing = await runtime.forms()

    assert [form.id for form in listing.value.forms] == [ZOO, CANTEEN]
    assert (listing.value.truncated, listing.status) == (False, "miss")


async def test_each_account_lists_only_the_forms_it_was_sent(harness: Harness) -> None:
    registry = harness.registry()

    assert (await registry.get("pablo").forms()).value.forms == ()
    assert len((await registry.get("marta").forms()).value.forms) == 2


async def test_a_list_of_forms_is_read_once_however_often_it_is_asked_for(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    first = await runtime.forms()
    calls = len(harness.sim.requests)

    second = await runtime.forms()

    assert (first.status, second.status) == ("miss", "hit")
    assert second.value == first.value
    assert len(harness.sim.requests) == calls


async def test_a_list_of_forms_is_read_again_after_five_minutes(
    harness: Harness, clock: ManualClock
) -> None:
    runtime = harness.registry().get("marta")
    await runtime.forms()

    clock.advance(299)
    assert (await runtime.forms()).status == "hit"
    clock.advance(2)

    assert (await runtime.forms()).status == "miss"


async def test_a_fresh_look_sees_a_form_that_arrived_since(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    before = await runtime.forms()
    harness.deliver(DEMO_USER_A, A_NEW_FORM)

    stale = await runtime.forms()
    fresh = await runtime.forms(fresh=True)

    assert stale.value == before.value
    assert fresh.status == "bypass"
    assert [form.id for form in fresh.value.forms] == [A_NEW_FORM.guid, ZOO, CANTEEN]


async def test_forms_and_messages_are_kept_under_keys_of_their_own(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    forms = await runtime.forms()
    messages = await runtime.messages("received")

    assert (forms.status, messages.status) == ("miss", "miss")
    assert {form.id for form in forms.value.forms}.isdisjoint(
        {message.id for message in messages.value.messages}
    )
    assert (await runtime.forms()).value == forms.value
    assert (await runtime.messages("received")).value == messages.value


async def test_a_form_is_its_row_in_the_list_joined_to_its_words(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    row = (await runtime.forms()).value.forms[0]

    found = (await runtime.form(ZOO)).value

    assert found.model_dump(include=set(FormSummary.model_fields)) == row.model_dump()
    assert found.sent_at.isoformat() == "2026-10-16T10:00:00+02:00"
    assert found.body.text.startswith("La clase de Lucía irá al zoo")
    assert found.child_names == "Lucía"


async def test_the_row_is_the_list_as_it_is_now_even_when_the_words_are_older(
    harness: Harness, clock: ManualClock
) -> None:
    runtime = harness.registry().get("marta")
    await runtime.forms()
    clock.advance(200)
    first = await runtime.form(ZOO)
    clock.advance(101)
    harness.revise(DEMO_USER_A, ZOO, expires="2026-11-15")

    second = await runtime.form(ZOO)

    assert first.status == "miss"
    assert 200 <= first.age < 201
    assert second.value.expires_on == date(2026, 11, 15)
    assert second.value.body == first.value.body
    assert second.status == "miss"
    assert 101 <= second.age < 103


async def test_a_form_is_found_by_its_id_in_any_letter_case(harness: Harness) -> None:
    runtime = harness.registry().get("marta")

    found = await runtime.form(ZOO.upper())

    assert found.value.id == ZOO


async def test_the_words_of_a_form_are_stored_and_read_again_when_their_time_is_up(
    harness: Harness, clock: ManualClock
) -> None:
    runtime = harness.registry(harness.settings(cache=CacheTtls(forms=60))).get("marta")
    first = await runtime.form(ZOO)
    reads = harness.requests_to(MESSAGE_DATA)

    clock.advance(59)
    second = await runtime.form(ZOO)
    clock.advance(1)
    third = await runtime.form(ZOO)

    assert [answer.status for answer in (first, second, third)] == ["miss", "hit", "miss"]
    assert harness.requests_to(MESSAGE_DATA) == reads + 1


async def test_a_time_to_live_of_zero_turns_the_store_of_forms_off(harness: Harness) -> None:
    runtime = harness.registry(harness.settings(cache=CacheTtls(forms=0))).get("marta")

    await runtime.form(ZOO)
    await runtime.form(ZOO)

    assert harness.requests_to(MESSAGE_DATA) == 2


@pytest.mark.parametrize(
    "reference", ["", "form", "5afe0000-0000-4000-8000-00000000140", f"{ZOO}0", f" {ZOO}"]
)
async def test_what_is_no_form_id_is_not_found_without_asking_the_portal(
    harness: Harness, reference: str
) -> None:
    runtime = harness.registry().get("marta")

    with pytest.raises(NotFoundError) as raised:
        await runtime.form(reference)

    assert (raised.value.kind, raised.value.reference) == ("form", reference)
    assert len(harness.sim.requests) == 0


async def test_a_form_the_list_does_not_hold_is_not_found_and_its_page_is_never_opened(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    unknown = synthetic_guid(0x9999)

    with pytest.raises(NotFoundError) as raised:
        await runtime.form(unknown)

    assert (raised.value.kind, raised.value.reference) == ("form", unknown)
    assert harness.requests_to("Comunicado.aspx") == 0
    assert harness.requests_to(MESSAGE_DATA) == 0


async def test_a_message_is_no_form_and_a_form_is_no_message(harness: Harness) -> None:
    runtime = harness.registry().get("marta")

    with pytest.raises(NotFoundError) as as_a_form:
        await runtime.form(UNREAD)
    with pytest.raises(NotFoundError) as as_a_message:
        await runtime.message("received", ZOO)

    assert as_a_form.value.kind == "form"
    assert as_a_message.value.kind == "message"
    assert harness.requests_to(MESSAGE_DATA) == 0


async def test_an_account_cannot_read_a_form_of_another_account(harness: Harness) -> None:
    registry = harness.registry()
    harness.deliver(DEMO_USER_B, A_NEW_FORM)

    assert (await registry.get("pablo").form(A_NEW_FORM.guid)).value.id == A_NEW_FORM.guid
    with pytest.raises(NotFoundError):
        await registry.get("marta").form(A_NEW_FORM.guid, fresh=True)


async def test_a_form_that_arrived_since_is_found_only_after_a_fresh_look(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    await runtime.forms()
    harness.deliver(DEMO_USER_A, A_NEW_FORM)

    with pytest.raises(NotFoundError):
        await runtime.form(A_NEW_FORM.guid)
    found = await runtime.form(A_NEW_FORM.guid, fresh=True)

    assert found.value.subject == "Autorización para la visita al huerto"


async def test_a_fresh_look_reads_the_list_and_the_words_again(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    await runtime.form(ZOO)
    lists, pages = harness.requests_to("Comunicados.aspx"), harness.requests_to(MESSAGE_DATA)

    again = await runtime.form(ZOO, fresh=True)

    assert again.status == "bypass"
    assert harness.requests_to("Comunicados.aspx") > lists
    assert harness.requests_to(MESSAGE_DATA) == pages + 1


async def test_many_requests_for_one_form_share_one_read(harness: Harness) -> None:
    runtime = harness.registry().get("marta")

    answers = await asyncio.gather(*(runtime.form(ZOO) for _ in range(8)))

    assert {answer.status for answer in answers} == {"miss"}
    assert harness.requests_to(MESSAGE_DATA) == 1


async def test_forms_and_messages_read_at_the_same_moment_never_get_each_others_rows(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")

    forms, messages = await asyncio.gather(
        asyncio.gather(*(runtime.forms(fresh=True) for _ in range(4))),
        asyncio.gather(*(runtime.messages("received", fresh=True) for _ in range(4))),
    )

    assert [{form.id for form in answer.value.forms} for answer in forms] == [{ZOO, CANTEEN}] * 4
    assert not any(
        {ZOO, CANTEEN} & {message.id for message in answer.value.messages} for answer in messages
    )


async def test_the_words_of_forms_and_messages_share_one_store_of_a_fixed_size(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alexia_api.services.registry.MAX_CACHED_MESSAGES", 2)
    runtime = harness.registry().get("marta")
    await runtime.form(ZOO)
    await runtime.form(CANTEEN)
    await runtime.message("received", UNREAD)

    statuses = [
        (await runtime.message("received", UNREAD)).status,
        (await runtime.form(CANTEEN)).status,
        (await runtime.form(ZOO)).status,
    ]

    assert statuses == ["hit", "hit", "miss"]
