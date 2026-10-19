"""Reading one message from its page."""

import threading
from dataclasses import replace
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import pytest

from alexia_api.domain.errors import SchemaDrift, UnexpectedReply, WsRejected
from alexia_api.domain.ids import attachment_token, parse_message_id, portal_file_id
from alexia_api.domain.messages import (
    Attachment,
    Body,
    FolderName,
    Link,
    MessageContent,
    Translation,
)
from alexia_api.portal import wire
from alexia_api.portal.allowlist import GET_MESSAGE_DATA
from alexia_api.portal.body import Rendered, render_body
from alexia_api.portal.gateway import Gateway
from alexia_api.portal.message import message_path, open_message, read_message
from alexia_api.portal.session import Tx
from alexia_api.portal.ws import call_ws
from alexia_api.sim.app import MESSAGE_PATH, MESSAGES_PATH
from alexia_api.sim.mail import SimFile, SimTranslation
from alexia_api.sim.world import DEMO_PASSWORD_B, DEMO_USER_A, DEMO_USER_B, synthetic_guid
from tests.harness import Failure, Harness, listed_row, seeded

MADRID = ZoneInfo("Europe/Madrid")
DATA_PATH = "/ACWeb/WS_Data/WSComunicados.asmx/GetDatosPaginaComunicado"
DRIFT_WHERE = "ws:WSComunicados.GetDatosPaginaComunicado reply"


async def content_of(
    gateway: Gateway, number: int, folder: FolderName = "received"
) -> MessageContent:
    summary = await listed_row(gateway, number, folder)
    return await gateway.call(lambda tx: read_message(tx, summary))


async def test_reads_the_time_the_words_the_files_and_the_facts_of_a_message(
    harness: Harness,
) -> None:
    sent = seeded(0x1002)
    (file,) = sent.files

    content = await content_of(harness.gateway(), 0x1002)

    assert content.sent_at == datetime(2026, 10, 14, 17, 40, tzinfo=MADRID)
    assert content.sent_at.utcoffset() == timedelta(hours=2)
    assert content.body.text == (
        "Adjuntamos la autorización para la excursión al museo.\n\n"
        "Por favor, responda a la encuesta antes del 25 de octubre en este formulario "
        "(https://forms.office.com/r/ejemplo)."
    )
    assert not content.body.simplified
    assert content.links == (
        Link(url="https://forms.office.com/r/ejemplo", host="forms.office.com", kind="form"),
    )
    assert content.attachments == (
        Attachment(
            id=attachment_token(file.id), name="Autorización museo.pdf", size=len(file.data)
        ),
    )
    assert content.child_names == "Lucía, Mateo"
    assert content.can_reply is False
    assert content.translations == ()


async def test_a_file_id_with_a_slash_and_a_space_becomes_a_token_that_reads_back(
    harness: Harness,
) -> None:
    (file,) = seeded(0x1002).files

    content = await content_of(harness.gateway(), 0x1002)

    (attachment,) = content.attachments
    assert "/" in file.id
    assert " " in file.id
    assert portal_file_id(attachment.id) == file.id


async def test_the_time_is_wall_time_in_the_zone_of_the_session(harness: Harness) -> None:
    auckland = ZoneInfo("Pacific/Auckland")

    content = await content_of(harness.gateway(zone=auckland), 0x1002)

    assert content.sent_at == datetime(2026, 10, 14, 17, 40, tzinfo=auckland)
    assert content.sent_at.utcoffset() == timedelta(hours=13)


async def test_the_offset_follows_daylight_saving_time(harness: Harness) -> None:
    winter = replace(
        seeded(0x1002), guid=synthetic_guid(0x1200), date="2026-01-15", time="09:00", files=()
    )
    harness.deliver(DEMO_USER_A, winter)

    content = await content_of(harness.gateway(), 0x1200)

    assert content.sent_at.isoformat() == "2026-01-15T09:00:00+01:00"


async def test_a_list_a_bold_word_and_a_video_link_survive(harness: Harness) -> None:
    content = await content_of(harness.gateway(), 0x1001)

    assert "<strong>reto de matemáticas</strong>" in content.body.html
    assert "- Resolver los tres problemas de la ficha." in content.body.text
    assert content.links == (
        Link(url="https://www.youtube.com/watch?v=ejemplo", host="youtube.com", kind="video"),
    )
    assert content.child_names == "Lucía"
    assert content.can_reply is True


async def test_a_table_reads_as_rows_of_cells(harness: Harness) -> None:
    content = await content_of(harness.gateway(), 0x1003)

    assert content.body.text.splitlines()[-3:] == [
        "Día | Clase",
        "Lunes | Matemáticas",
        "Miércoles | Música",
    ]


async def test_an_address_written_in_the_words_is_a_link_too(harness: Harness) -> None:
    content = await content_of(harness.gateway(), 0x1004)

    assert [(link.kind, link.url) for link in content.links] == [
        ("video_call", "https://meet.google.com/abc-defg-hij"),
        ("email", "mailto:tutoria@example.test"),
    ]


async def test_a_picture_the_message_carries_stays_and_a_numbered_list_keeps_its_numbers(
    harness: Harness,
) -> None:
    content = await content_of(harness.gateway(), 0x1005)

    assert content.body.html.count("<img ") == 1
    assert 'src="data:image/png;base64,' in content.body.html
    assert "[image: Logotipo del colegio]" in content.body.text
    assert "1. Inicio de curso, 8 de septiembre." in content.body.text
    assert "2. Vacaciones de Navidad" in content.body.text


async def test_the_second_version_of_a_message_is_a_translation(harness: Harness) -> None:
    content = await content_of(harness.gateway(), 0x1007)

    assert content.translations == (
        Translation(
            slot=2,
            subject="Parents' meeting",
            body=Body(
                html="<p>Dear families, the meeting will take place on 20 September at 16:20.</p>",
                text="Dear families, the meeting will take place on 20 September at 16:20.",
                simplified=False,
            ),
        ),
    )


async def test_both_extra_versions_come_in_order_and_an_empty_one_is_not_a_translation(
    harness: Harness,
) -> None:
    versions = (
        SimTranslation("  Segunda   versión ", "<p>dos</p>"),
        SimTranslation("Tercera", ""),
    )
    harness.deliver(
        DEMO_USER_A, replace(seeded(0x1007), guid=synthetic_guid(0x1201), translations=versions)
    )
    harness.deliver(
        DEMO_USER_A,
        replace(
            seeded(0x1007),
            guid=synthetic_guid(0x1202),
            translations=(SimTranslation(" ", "  "), SimTranslation("", "<p>tres</p>")),
        ),
    )
    gateway = harness.gateway()

    both = await content_of(gateway, 0x1201)
    only_the_third = await content_of(gateway, 0x1202)

    assert [(item.slot, item.subject, item.body.text) for item in both.translations] == [
        (2, "Segunda versión", "dos"),
        (3, "Tercera", ""),
    ]
    assert [(item.slot, item.subject, item.body.text) for item in only_the_third.translations] == [
        (3, "", "tres")
    ]


async def test_a_message_that_names_no_child_has_none(harness: Harness) -> None:
    content = await content_of(harness.gateway(), 0x1008)

    assert content.child_names == "Lucía, Mateo"
    harness.deliver(
        DEMO_USER_A, replace(seeded(0x1008), guid=synthetic_guid(0x1203), child_names="  ")
    )
    assert (await content_of(harness.gateway(), 0x1203)).child_names is None


async def test_an_anonymous_message_has_no_sender_on_its_page_and_still_reads(
    harness: Harness,
) -> None:
    content = await content_of(harness.gateway(), 0x1006)

    assert content.can_reply is False
    assert [item.name for item in content.attachments] == ["Menú octubre.pdf"]


async def test_a_message_the_guardian_sent_reads_from_the_sent_folder(harness: Harness) -> None:
    content = await content_of(harness.gateway(), 0x2001, "sent")

    assert content.sent_at == datetime(2026, 10, 1, 20, 15, tzinfo=MADRID)
    assert content.body.text == "Ausencia de Lucía. Texto de ejemplo enviado por la familia."


async def test_the_words_of_a_hostile_message_are_cleaned_on_the_way_in(harness: Harness) -> None:
    hostile = replace(
        seeded(0x1008),
        guid=synthetic_guid(0x1204),
        body_html='<script>alert(1)</script><p onclick="steal()">hola</p>',
    )
    harness.deliver(DEMO_USER_A, hostile)

    content = await content_of(harness.gateway(), 0x1204)

    assert content.body.html == "<p>hola</p>"
    assert content.body.text == "hola"


async def test_the_words_are_cleaned_off_the_thread_of_the_event_loop(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    threads: list[int] = []

    def watched(raw: str) -> Rendered:
        threads.append(threading.get_ident())
        return render_body(raw)

    monkeypatch.setattr("alexia_api.portal.message.render_body", watched)

    await content_of(harness.gateway(), 0x1007)

    assert len(threads) == 2
    assert threading.get_ident() not in threads


async def test_it_opens_the_page_and_then_asks_for_its_data(harness: Harness) -> None:
    gateway = harness.gateway()
    row = await listed_row(gateway, 0x1001)
    before = len(harness.sim.requests)

    await gateway.call(lambda tx: read_message(tx, row))

    made = harness.sim.requests[before:]
    assert [(request.method, request.path) for request in made] == [
        ("GET", MESSAGE_PATH),
        ("POST", DATA_PATH),
    ]
    assert made[0].query == message_path(row.id).partition("?")[2]
    assert parse_qs(made[0].query, keep_blank_values=True) == {
        "GuidComunicadoOrigen": [row.id],
        "TipoComunicado": ["N"],
        "AccionComunicado": ["1"],
        "DestsInicialesCom": [""],
        "TxtDefaultCom": [""],
        "AccionExtraCom": [""],
    }


@pytest.mark.parametrize(
    "subject",
    [
        "reto de matemáticas",
        "  Reto   de\tmatemáticas ",
        "Reto de",
        "Reto de matemáticas, segunda parte",
    ],
)
async def test_the_subject_may_differ_from_the_row_in_case_spacing_and_length(
    harness: Harness, subject: str
) -> None:
    gateway = harness.gateway()
    row = (await listed_row(gateway, 0x1001)).model_copy(update={"subject": subject})

    content = await gateway.call(lambda tx: read_message(tx, row))

    assert content.body.text.startswith("Hola familias")


@pytest.mark.parametrize(
    "changes",
    [
        {"subject": "Otro asunto"},
        {"subject": "Matemáticas, reto"},
        {"subject": " "},
        {"received_on": date(2026, 10, 16)},
        {"sender": "Alguien Distinto"},
        {"sender": ""},
    ],
    ids=["subject", "subject-in-another-order", "no-subject", "day", "sender", "no-sender"],
)
async def test_a_page_that_is_not_the_message_of_the_row_is_refused(
    harness: Harness, failure: Failure, changes: dict[str, object]
) -> None:
    gateway = harness.gateway()
    row = (await listed_row(gateway, 0x1001)).model_copy(update=changes)

    detail = await failure(gateway.call(lambda tx: read_message(tx, row)))

    assert detail == UnexpectedReply(where="message page does not match the list row")


async def test_a_message_with_no_subject_reads_because_a_blank_matches_a_blank(
    harness: Harness,
) -> None:
    harness.deliver(DEMO_USER_A, replace(seeded(0x1008), guid=synthetic_guid(0x1206), subject=""))

    content = await content_of(harness.gateway(), 0x1206)

    assert content.can_reply is False


async def test_the_data_call_answers_only_for_a_message_the_session_has_open(
    harness: Harness, failure: Failure
) -> None:
    gateway = harness.gateway()
    row = await listed_row(gateway, 0x1001)

    detail = await failure(
        gateway.call(
            lambda tx: call_ws(
                tx, GET_MESSAGE_DATA, wire.EmptyParams(), referer=tx.absolute(message_path(row.id))
            )
        )
    )

    assert detail == WsRejected(call="WSComunicados.GetDatosPaginaComunicado", status=500)


async def test_the_data_call_must_come_from_the_page_of_the_open_message(
    harness: Harness, failure: Failure
) -> None:
    gateway = harness.gateway()
    row = await listed_row(gateway, 0x1001)

    async def from_the_list(tx: Tx) -> object:
        await open_message(tx, row.id)
        return await call_ws(
            tx, GET_MESSAGE_DATA, wire.EmptyParams(), referer=tx.absolute(MESSAGES_PATH)
        )

    detail = await failure(gateway.call(from_the_list))

    assert detail == WsRejected(call="WSComunicados.GetDatosPaginaComunicado", status=500)


async def test_a_message_the_school_takes_back_after_its_page_opened_is_a_rejected_call(
    harness: Harness, failure: Failure
) -> None:
    gateway = harness.gateway()
    row = await listed_row(gateway, 0x1001)

    async def taken_back(tx: Tx) -> object:
        await open_message(tx, row.id)
        harness.withdraw(DEMO_USER_A, row.id)
        return await call_ws(
            tx, GET_MESSAGE_DATA, wire.EmptyParams(), referer=tx.absolute(message_path(row.id))
        )

    detail = await failure(gateway.call(taken_back))

    assert detail == WsRejected(call="WSComunicados.GetDatosPaginaComunicado", status=500)


async def test_a_message_the_family_does_not_have_cannot_be_opened(
    harness: Harness, failure: Failure
) -> None:
    other_family = harness.gateway(
        account="family-b", credentials=harness.credentials(DEMO_USER_B, DEMO_PASSWORD_B)
    )
    theirs = await listed_row(other_family, 0x1101)
    ours = harness.gateway()

    detail = await failure(ours.call(lambda tx: open_message(tx, theirs.id)))

    assert detail == UnexpectedReply(where="page:message HTTP 500")
    nobody = parse_message_id(synthetic_guid(0x9999))
    assert await failure(ours.call(lambda tx: open_message(tx, nobody))) == detail


@pytest.mark.parametrize("time", ["25:99", "24:00"])
async def test_a_time_that_is_not_on_any_clock_is_schema_drift(
    harness: Harness, failure: Failure, time: str
) -> None:
    gateway = harness.gateway()
    row = await listed_row(gateway, 0x1001)
    harness.sim.options.message_time = time

    detail = await failure(gateway.call(lambda tx: read_message(tx, row)))

    assert detail == SchemaDrift(
        where="message publication time", sample=f"{row.received_on.isoformat()} {time}"
    )


@pytest.mark.parametrize("time", ["9:5", "09:05:00", "", "nine"])
async def test_a_time_in_another_shape_is_schema_drift(
    harness: Harness, failure: Failure, time: str
) -> None:
    gateway = harness.gateway()
    row = await listed_row(gateway, 0x1001)
    harness.sim.options.message_time = time

    detail = await failure(gateway.call(lambda tx: read_message(tx, row)))

    assert isinstance(detail, SchemaDrift)
    assert detail.where == DRIFT_WHERE


async def test_a_file_the_portal_lists_without_an_id_is_schema_drift(
    harness: Harness, failure: Failure
) -> None:
    nameless = SimFile(id="", name="a.pdf", data=b"x")
    harness.deliver(
        DEMO_USER_A, replace(seeded(0x1008), guid=synthetic_guid(0x1205), files=(nameless,))
    )

    detail = await failure(content_of(harness.gateway(), 0x1205))

    assert isinstance(detail, SchemaDrift)
    assert detail.where == DRIFT_WHERE


async def test_a_session_that_ended_is_replaced_and_the_reader_never_notices(
    harness: Harness,
) -> None:
    gateway = harness.gateway()
    row = await listed_row(gateway, 0x1001)
    harness.sim.expire_all_sessions()

    content = await gateway.call(lambda tx: read_message(tx, row))

    assert content.body.text.startswith("Hola familias")
    assert harness.sim.counters.login_attempts == 2
