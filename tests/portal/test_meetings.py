"""Reading the meetings of a child."""

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import pytest

from alexia_api.domain.errors import PortalError, SchemaDrift, UnexpectedReply
from alexia_api.domain.ids import parse_meeting_id, parse_student_id
from alexia_api.domain.meetings import MEETING_STATES, Meeting
from alexia_api.portal.grid import GridRow, read_grid_text
from alexia_api.portal.meetings import (
    MEETING_CELLS,
    MEETINGS_GRID,
    parse_meeting_row,
    parse_meetings,
    read_meetings,
    state_of,
)
from alexia_api.sim.app import SimOptions
from alexia_api.sim.world import synthetic_guid
from tests.harness import Failure, Harness

MADRID = ZoneInfo("Europe/Madrid")
BOGOTA = ZoneInfo("America/Bogota")
GUID = synthetic_guid(0x7301)
PAGE_TEXT = "the whole page"


def icon(title: str) -> str:
    return f'<img src="https://static.sim.invalid/e.png" alt="{title}" title="{title}" />'


BASE: tuple[object, ...] = (
    GUID,
    icon("Aceptada"),
    icon("Participantes"),
    "&nbsp;",
    "10",
    "20/10/2025",
    "16:00",
    "Marta Ejemplo",
    "Ana Muestra Tutora",
    "Lucía Ejemplo Muestra",
    "&nbsp;",
    "&nbsp;",
)


def row_of(changes: Mapping[int, object] | None = None, *, row_id: str = GUID) -> GridRow:
    cell = list(BASE)
    for index, value in (changes or {}).items():
        cell[index] = value
    return GridRow(id=row_id, cell=cell)


def parsed(
    changes: Mapping[int, object] | None = None, *, row_id: str = GUID, zone: ZoneInfo = MADRID
) -> Meeting:
    return parse_meeting_row(row_of(changes, row_id=row_id), 0, PAGE_TEXT, zone)


def drift_of(row: GridRow, index: int = 0) -> SchemaDrift:
    with pytest.raises(PortalError) as raised:
        parse_meeting_row(row, index, PAGE_TEXT, MADRID)
    detail = raised.value.detail
    assert isinstance(detail, SchemaDrift)
    assert detail.sample == PAGE_TEXT
    return detail


def test_reads_every_field_of_a_row() -> None:
    assert parsed() == Meeting(
        id=parse_meeting_id(GUID),
        state="accepted",
        state_label="Aceptada",
        starts_at=datetime(2025, 10, 20, 16, 0, tzinfo=MADRID),
        requested_by="Marta Ejemplo",
        staff="Ana Muestra Tutora",
        note=None,
    )


def test_reads_a_meeting_that_has_a_note() -> None:
    meeting = parsed(
        {7: "Ana Muestra Tutora", 8: "Carlos Ejemplo Profesor", 10: "Traer el boletín."}
    )

    assert (meeting.requested_by, meeting.staff, meeting.note) == (
        "Ana Muestra Tutora",
        "Carlos Ejemplo Profesor",
        "Traer el boletín.",
    )


@pytest.mark.parametrize(("index", "field"), [(7, "requested_by"), (8, "staff"), (10, "note")])
@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("Texto", "Texto"),
        ("  Dos   palabras\n", "Dos palabras"),
        ("<b>Negrita</b> &amp; más", "Negrita & más"),
        ("Tom&nbsp;Demo", "Tom Demo"),
        ("", None),
        ("&nbsp", None),
        ("&nbsp;", None),
        ("   ", None),
    ],
)
def test_the_optional_texts_are_tidied_and_empty_means_none(
    index: int, field: str, html: str, expected: str | None
) -> None:
    assert getattr(parsed({index: html}), field) == expected


@pytest.mark.parametrize(
    ("html", "label", "state"),
    [
        (icon("Aceptada"), "Aceptada", "accepted"),
        (icon("  Cancelada  "), "Cancelada", "cancelled"),
        ('<img src="x.png" alt="Otra cosa" title="Rechazada" />', "Rechazada", "declined"),
        ('<a href="#"><img title="Realizada"></a>', "Realizada", "done"),
        ('<i class="icono" title="Cancelada"></i>', "Cancelada", "cancelled"),
        ('<span title="Cancelada">Pendiente</span>', "Cancelada", "cancelled"),
        ("Realizada", "Realizada", "done"),
        ('<span title="">Pendiente</span>', "Pendiente", "requested"),
        ("<b>Solicitada</b>", "Solicitada", "requested"),
        (icon("En   revisión"), "En revisión", "unknown"),
        ("&nbsp;", "", "unknown"),
        ("", "", "unknown"),
    ],
)
def test_the_state_is_the_title_of_the_icon_or_else_the_words_of_the_cell(
    html: str, label: str, state: str
) -> None:
    meeting = parsed({1: html})

    assert (meeting.state_label, meeting.state) == (label, state)


@pytest.mark.parametrize(
    ("label", "state"),
    [
        ("Aceptada", "accepted"),
        ("ACEPTADA", "accepted"),
        ("aceptada", "accepted"),
        ("Confirmada", "accepted"),
        ("Cancelada", "cancelled"),
        ("Anulada", "cancelled"),
        ("Rechazada", "declined"),
        ("Denegada", "declined"),
        ("Realizada", "done"),
        ("Celebrada", "done"),
        ("Solicitada", "requested"),
        ("Pendiente", "requested"),
        ("Pendiente de confirmar", "requested"),
        ("Propuesta", "requested"),
        ("Cancelada y rechazada", "cancelled"),
        ("Cancelada, solicitada por la familia", "cancelled"),
        ("Rechazada, no aceptada", "declined"),
        ("Rechazada, pendiente de otra fecha", "declined"),
        ("Aceptada y realizada", "accepted"),
        ("Aceptada, pendiente de sala", "accepted"),
        ("Realizada tras ser solicitada", "done"),
        ("Aplazada", "unknown"),
        ("En revisión", "unknown"),
        ("", "unknown"),
    ],
)
def test_a_label_reads_as_the_first_state_it_has_a_word_for(label: str, state: str) -> None:
    assert state_of(label) == state


def test_every_state_of_the_model_can_be_read_from_a_label() -> None:
    labels = ["Aceptada", "Cancelada", "Rechazada", "Realizada", "Solicitada", "Algo nuevo"]

    assert {state_of(label) for label in labels} == set(MEETING_STATES)


@pytest.mark.parametrize(
    ("text", "hour", "minute"),
    [
        ("16:00", 16, 0),
        ("9:05", 9, 5),
        (" 16:30 ", 16, 30),
        ("00:00", 0, 0),
        ("23:59", 23, 59),
        ("<b>17:45</b>", 17, 45),
    ],
)
def test_the_start_time_is_read_with_one_or_two_digits_for_the_hour(
    text: str, hour: int, minute: int
) -> None:
    assert parsed({6: text}).starts_at == datetime(2025, 10, 20, hour, minute, tzinfo=MADRID)


@pytest.mark.parametrize(
    "text", ["", "&nbsp;", "25:00", "24:00", "16:60", "4pm", "16:00:00", "16.00", "16:0", "16h"]
)
def test_a_start_time_that_is_not_a_clock_time_is_schema_drift(text: str) -> None:
    assert drift_of(row_of({6: text})).where == "meeting row 0: start time"


def test_a_meeting_for_a_whole_group_starts_at_midnight_and_keeps_the_time_in_its_note() -> None:
    meeting = parsed({6: "00:00", 10: "Reunión de aula a las 17:30."})

    assert meeting.starts_at == datetime(2025, 10, 20, 0, 0, tzinfo=MADRID)
    assert meeting.note == "Reunión de aula a las 17:30."


def test_the_date_may_sit_in_markup_and_spaces() -> None:
    assert parsed({5: " <b>20/10/2025</b> "}).starts_at.date().isoformat() == "2025-10-20"


@pytest.mark.parametrize("text", ["31/02/2025", "", "2025-10-20", "&nbsp", "20/10/25", "1/10/2025"])
def test_a_date_that_is_not_a_list_date_is_schema_drift(text: str) -> None:
    assert drift_of(row_of({5: text})).where == "meeting row 0: date"


def test_a_meeting_starts_in_the_zone_it_is_read_in() -> None:
    meeting = parsed(zone=BOGOTA)

    assert meeting.starts_at == datetime(2025, 10, 20, 16, 0, tzinfo=BOGOTA)
    assert meeting.starts_at.utcoffset() == timedelta(hours=-5)
    assert parsed().starts_at.utcoffset() == timedelta(hours=2)
    assert parsed({5: "20/01/2026"}).starts_at.utcoffset() == timedelta(hours=1)


@pytest.mark.parametrize("count", [0, 1, 11, 13, 14])
def test_a_row_must_have_twelve_cells(count: int) -> None:
    cell = [*BASE[:count], *[""] * max(0, count - len(BASE))]

    detail = drift_of(GridRow(id=GUID, cell=cell), index=3)

    assert MEETING_CELLS == 12
    assert detail.where == f"meeting row 3: {count} cells instead of 12"


@pytest.mark.parametrize("value", [None, 1, True, ["x"], {"a": 1}])
def test_a_cell_that_is_not_text_is_schema_drift(value: object) -> None:
    assert drift_of(row_of({8: value})).where == "meeting row 0: a cell is not text"


@pytest.mark.parametrize(
    ("row_id", "first"),
    [
        (synthetic_guid(0x7302), GUID),
        ("not-a-guid", GUID),
        (GUID, "not-a-guid"),
        ("", ""),
    ],
)
def test_the_row_id_and_the_first_cell_must_name_one_meeting(row_id: str, first: str) -> None:
    detail = drift_of(row_of({0: first}, row_id=row_id))

    assert detail.where == "meeting row 0: the row id and the first cell disagree"


def test_the_id_may_differ_in_case_between_the_row_and_the_cell() -> None:
    assert parsed({0: GUID.upper()}, row_id=GUID).id == GUID


def page_text(*rows: GridRow) -> str:
    return json.dumps(
        {
            "page": 1,
            "total": 1,
            "records": len(rows),
            "rows": [{"id": row.id, "cell": row.cell} for row in rows],
            "userdata": {},
        }
    )


def test_a_grid_is_read_in_the_order_the_meetings_take_place_whatever_order_the_portal_used() -> (
    None
):
    september, october, january = (synthetic_guid(number) for number in (0x7302, 0x7301, 0x7303))
    text = page_text(
        row_of({0: january, 5: "15/01/2026"}, row_id=january),
        row_of({0: october}, row_id=october),
        row_of({0: september, 5: "25/09/2025"}, row_id=september),
    )

    assert [meeting.id for meeting in parse_meetings(text, MADRID)] == [september, october, january]


def test_two_meetings_on_one_day_are_ordered_by_their_start_time() -> None:
    afternoon, morning = synthetic_guid(0x7301), synthetic_guid(0x7302)
    text = page_text(
        row_of({0: afternoon, 6: "17:00"}, row_id=afternoon),
        row_of({0: morning, 6: "9:05"}, row_id=morning),
    )

    assert [meeting.id for meeting in parse_meetings(text, MADRID)] == [morning, afternoon]


def test_two_meetings_at_one_time_are_ordered_by_id() -> None:
    first, second = synthetic_guid(0x7301), synthetic_guid(0x7302)
    text = page_text(row_of({0: second}, row_id=second), row_of({0: first}, row_id=first))

    assert [meeting.id for meeting in parse_meetings(text, MADRID)] == [first, second]


def test_a_grid_without_rows_has_no_meetings() -> None:
    assert parse_meetings(page_text(), MADRID) == ()


def test_a_grid_names_the_row_it_cannot_read() -> None:
    text = page_text(row_of(), row_of({5: "soon"}))

    with pytest.raises(PortalError) as raised:
        parse_meetings(text, MADRID)

    assert raised.value.detail == SchemaDrift(where="meeting row 1: date", sample=text)


def test_a_grid_that_is_not_json_is_schema_drift() -> None:
    with pytest.raises(PortalError) as raised:
        parse_meetings("<html></html>", MADRID)

    assert raised.value.detail == SchemaDrift(
        where="meetings grid is not JSON", sample="<html></html>"
    )


async def read(harness: Harness, first_name: str) -> tuple[Meeting, ...]:
    gateway, student = harness.guardian_of(first_name)
    return await gateway.call(lambda tx: read_meetings(tx, student))


async def test_reads_the_meetings_of_a_child_in_the_order_they_take_place(
    harness: Harness,
) -> None:
    assert await read(harness, "Lucía") == (
        Meeting(
            id=parse_meeting_id(synthetic_guid(0x7302)),
            state="done",
            state_label="Realizada",
            starts_at=datetime(2025, 9, 25, 17, 0, tzinfo=MADRID),
            requested_by="Ana Muestra Tutora",
            staff="Ana Muestra Tutora",
            note="Seguimiento del inicio de curso.",
        ),
        Meeting(
            id=parse_meeting_id(synthetic_guid(0x7301)),
            state="accepted",
            state_label="Aceptada",
            starts_at=datetime(2025, 10, 20, 16, 0, tzinfo=MADRID),
            requested_by="Marta Ejemplo",
            staff="Ana Muestra Tutora",
            note=None,
        ),
        Meeting(
            id=parse_meeting_id(synthetic_guid(0x7303)),
            state="cancelled",
            state_label="Cancelada",
            starts_at=datetime(2026, 1, 15, 15, 30, tzinfo=MADRID),
            requested_by="Marta Ejemplo",
            staff="Carlos Ejemplo Profesor",
            note="La familia no puede asistir.",
        ),
    )


async def test_the_portal_lists_january_first_and_the_reader_does_not(harness: Harness) -> None:
    gateway, student = harness.guardian_of("Lucía")

    text = await gateway.call(lambda tx: read_grid_text(tx, MEETINGS_GRID, student))

    assert [row["id"] for row in json.loads(text)["rows"]] == [
        synthetic_guid(0x7303),
        synthetic_guid(0x7302),
        synthetic_guid(0x7301),
    ]


async def test_reads_a_meeting_that_still_waits_for_an_answer(harness: Harness) -> None:
    (waiting,) = await read(harness, "Hugo")

    assert waiting == Meeting(
        id=parse_meeting_id(synthetic_guid(0x7311)),
        state="requested",
        state_label="Pendiente",
        starts_at=datetime(2025, 11, 10, 17, 0, tzinfo=MADRID),
        requested_by="Pablo Prueba",
        staff="Ana Muestra Tutora",
        note=None,
    )


async def test_reads_a_meeting_for_a_whole_class(harness: Harness) -> None:
    (class_meeting,) = await read(harness, "Alba")

    assert class_meeting.starts_at == datetime(2025, 9, 18, 0, 0, tzinfo=MADRID)
    assert class_meeting.note == "Reunión de aula a las 17:30."
    assert class_meeting.state == "done"


async def test_a_child_with_no_meetings_has_none(harness: Harness) -> None:
    assert await read(harness, "Mateo") == ()


async def test_each_child_has_its_own_meetings(harness: Harness) -> None:
    lucia = {meeting.id for meeting in await read(harness, "Lucía")}
    hugo = {meeting.id for meeting in await read(harness, "Hugo")}

    assert hugo == {synthetic_guid(0x7311)}
    assert lucia.isdisjoint(hugo)


async def test_meetings_are_placed_in_the_zone_of_the_session(harness: Harness) -> None:
    gateway = harness.gateway(account="marta", credentials=harness.credentials(), zone=BOGOTA)
    _, student = harness.guardian_of("Lucía")

    found = await gateway.call(lambda tx: read_meetings(tx, student))

    assert found[1].starts_at == datetime(2025, 10, 20, 16, 0, tzinfo=BOGOTA)


async def test_opens_the_page_of_the_child_and_then_reads_the_rows(harness: Harness) -> None:
    gateway, student = harness.guardian_of("Lucía")
    await gateway.call(lambda tx: read_meetings(tx, student))

    asked = [
        parse_qs(request.query)
        for request in harness.sim.requests
        if request.path == MEETINGS_GRID.page
    ]
    context = {
        "GuidObjeto": [student],
        "ObjetoTipo": ["6"],
        "master": ["3"],
        "contexto_pagina": ["1"],
    }
    assert len(asked) == 2
    page, feed = asked
    assert page == context
    assert {name: feed[name] for name in context} == context
    assert feed["jqGridID"] == [MEETINGS_GRID.grid_id]
    assert (feed["_search"], feed["rows"], feed["page"]) == (["false"], ["500"], ["1"])
    assert (feed["sidx"], feed["sord"]) == (["Unbound_Mes asc, Fecha"], ["asc"])
    assert feed["nd"][0].isdecimal()


async def test_a_student_the_portal_does_not_list_is_refused_and_not_read_as_empty(
    harness: Harness, failure: Failure
) -> None:
    stranger = parse_student_id(synthetic_guid(0x999))

    detail = await failure(harness.gateway().call(lambda tx: read_meetings(tx, stranger)))

    assert detail == UnexpectedReply(where="page:meetings-page HTTP 500")


@pytest.mark.parametrize(
    ("options", "where"),
    [
        (SimOptions(grid_cell_count=11), "meeting row 0: 11 cells instead of 12"),
        (SimOptions(grid_cell_count=13), "meeting row 0: 13 cells instead of 12"),
        (SimOptions(grid_bad_date=True), "meeting row 0: date"),
        (SimOptions(grid_not_json=True), "meetings grid is not JSON"),
    ],
)
async def test_a_grid_the_portal_changed_is_schema_drift(
    harness: Harness, failure: Failure, options: SimOptions, where: str
) -> None:
    harness.sim.options = options
    gateway, student = harness.guardian_of("Lucía")

    detail = await failure(gateway.call(lambda tx: read_meetings(tx, student)))

    assert isinstance(detail, SchemaDrift)
    assert detail.where == where
