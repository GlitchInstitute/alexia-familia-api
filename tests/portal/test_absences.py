"""Reading the absences of a child."""

import json
from collections.abc import Mapping
from datetime import date
from urllib.parse import parse_qs

import pytest

from alexia_api.domain.absences import Absence
from alexia_api.domain.errors import PortalError, SchemaDrift, UnexpectedReply
from alexia_api.domain.ids import parse_absence_id, parse_student_id
from alexia_api.portal.absences import (
    ABSENCE_CELLS,
    ABSENCES_GRID,
    parse_absence_row,
    parse_absences,
    read_absences,
)
from alexia_api.portal.grid import GridRow
from alexia_api.sim.app import SimOptions
from alexia_api.sim.world import synthetic_guid
from tests.harness import Failure, Harness

GUID = synthetic_guid(0x7501)
PAGE_TEXT = "the whole page"
UNCHECKED = '<input type="checkbox" value="false" offval="no" disabled="true"/>'
CHECKED = '<input type="checkbox" checked="checked" value="true" offval="no" disabled="true"/>'

BASE: tuple[object, ...] = (
    GUID,
    "&nbsp;",
    "14/10/2026",
    "",
    "10 - octubre",
    "&nbsp;",
    "Mateo Ejemplo Muestra",
    "Tutoría",
    "Rosa Prueba",
    "Falta de asistencia",
    "&nbsp;",
    "No",
    "&nbsp;",
    UNCHECKED,
)


def row_of(changes: Mapping[int, object] | None = None, *, row_id: str = GUID) -> GridRow:
    cell = list(BASE)
    for index, value in (changes or {}).items():
        cell[index] = value
    return GridRow(id=row_id, cell=cell)


def parsed(changes: Mapping[int, object] | None = None, *, row_id: str = GUID) -> Absence:
    return parse_absence_row(row_of(changes, row_id=row_id), 0, PAGE_TEXT)


def drift_of(row: GridRow, index: int = 0) -> SchemaDrift:
    with pytest.raises(PortalError) as raised:
        parse_absence_row(row, index, PAGE_TEXT)
    detail = raised.value.detail
    assert isinstance(detail, SchemaDrift)
    assert detail.sample == PAGE_TEXT
    return detail


def test_reads_every_field_of_a_row() -> None:
    assert parsed() == Absence(
        id=parse_absence_id(GUID),
        occurred_on=date(2026, 10, 14),
        hour=None,
        area="Tutoría",
        teacher="Rosa Prueba",
        incident="Falta de asistencia",
        note=None,
        justifiable=True,
        justified=False,
        justification=None,
        accepted=False,
    )


def test_reads_a_justified_late_arrival() -> None:
    absence = parsed(
        {
            1: '<img src="/i/no_justificable.png" alt="No justificable" />',
            2: "09/10/2026",
            5: "09:05",
            7: "Música",
            9: "Retraso",
            10: "Llegó tarde.",
            11: "Sí",
            12: "Cita médica",
            13: CHECKED,
        }
    )

    assert (absence.occurred_on, absence.hour, absence.area, absence.incident) == (
        date(2026, 10, 9),
        "09:05",
        "Música",
        "Retraso",
    )
    assert (absence.note, absence.justifiable, absence.justified) == ("Llegó tarde.", False, True)
    assert (absence.justification, absence.accepted) == ("Cita médica", True)


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("&nbsp;", True),
        ("", True),
        (" ", True),
        ("<span>x</span>", True),
        ('<img src="x.png">', False),
        ('<IMG src="x.png">', False),
        ('<a><img alt="No justificable"></a>', False),
    ],
)
def test_an_image_in_the_second_cell_marks_an_incident_that_cannot_be_justified(
    html: str, expected: bool
) -> None:
    assert parsed({1: html}).justifiable is expected


@pytest.mark.parametrize("index", [11, 13])
@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("Sí", True),
        ("SÍ", True),
        ("Si", True),
        (" sí ", True),
        ("True", True),
        ("1", True),
        ("No", False),
        ("NO", False),
        ("False", False),
        ("0", False),
        (CHECKED, True),
        ('<input type="checkbox" checked>', True),
        ('<input type="checkbox" checked="false">', True),
        (UNCHECKED, False),
        ('<input type="checkbox">', False),
        ("", None),
        ("&nbsp;", None),
        ("Quizá", None),
        ("2", None),
        ("<b>x</b>", None),
    ],
)
def test_a_yes_or_no_cell_reads_as_a_flag_or_as_unknown(
    index: int, html: str, expected: bool | None
) -> None:
    absence = parsed({index: html})

    assert (absence.justified if index == 11 else absence.accepted) is expected


@pytest.mark.parametrize(
    ("index", "field"),
    [(5, "hour"), (7, "area"), (8, "teacher"), (10, "note"), (12, "justification")],
)
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


def test_the_incident_is_decoded_and_tidied() -> None:
    assert parsed({9: "  <i>Falta</i>   de\n asistencia "}).incident == "Falta de asistencia"


def test_the_date_may_sit_in_markup_and_spaces() -> None:
    assert parsed({2: " <b>14/10/2026</b> "}).occurred_on == date(2026, 10, 14)


@pytest.mark.parametrize("text", ["31/02/2026", "", "2026-10-14", "&nbsp", "14/10/26", "1/10/2026"])
def test_a_date_that_is_not_a_list_date_is_schema_drift(text: str) -> None:
    assert drift_of(row_of({2: text})).where == "absence row 0: date"


@pytest.mark.parametrize("count", [0, 1, 13, 15])
def test_a_row_must_have_fourteen_cells(count: int) -> None:
    cell = [*BASE[:count], *[""] * max(0, count - len(BASE))]

    detail = drift_of(GridRow(id=GUID, cell=cell), index=3)

    assert ABSENCE_CELLS == 14
    assert detail.where == f"absence row 3: {count} cells instead of 14"


@pytest.mark.parametrize("value", [None, 1, True, ["x"], {"a": 1}])
def test_a_cell_that_is_not_text_is_schema_drift(value: object) -> None:
    assert drift_of(row_of({9: value})).where == "absence row 0: a cell is not text"


@pytest.mark.parametrize(
    ("row_id", "first"),
    [
        (synthetic_guid(0x7502), GUID),
        ("not-a-guid", GUID),
        (GUID, "not-a-guid"),
        ("", ""),
    ],
)
def test_the_row_id_and_the_first_cell_must_name_one_incident(row_id: str, first: str) -> None:
    detail = drift_of(row_of({0: first}, row_id=row_id))

    assert detail.where == "absence row 0: the row id and the first cell disagree"


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


def test_a_grid_is_read_row_by_row_in_the_order_the_portal_sent_it() -> None:
    other = synthetic_guid(0x7502)

    found = parse_absences(page_text(row_of(), row_of({0: other, 2: "13/10/2026"}, row_id=other)))

    assert [(absence.id, absence.occurred_on) for absence in found] == [
        (GUID, date(2026, 10, 14)),
        (other, date(2026, 10, 13)),
    ]


def test_a_grid_without_rows_has_no_absences() -> None:
    assert parse_absences(page_text()) == ()


def test_a_grid_names_the_row_it_cannot_read() -> None:
    text = page_text(row_of(), row_of({2: "soon"}))

    with pytest.raises(PortalError) as raised:
        parse_absences(text)

    assert raised.value.detail == SchemaDrift(where="absence row 1: date", sample=text)


def test_a_grid_that_is_not_json_is_schema_drift() -> None:
    with pytest.raises(PortalError) as raised:
        parse_absences("<html></html>")

    assert raised.value.detail == SchemaDrift(
        where="absences grid is not JSON", sample="<html></html>"
    )


async def read(harness: Harness, first_name: str) -> tuple[Absence, ...]:
    gateway, student = harness.guardian_of(first_name)
    return await gateway.call(lambda tx: read_absences(tx, student))


async def test_reads_the_absences_of_a_child_newest_first(harness: Harness) -> None:
    found = await read(harness, "Mateo")

    assert [
        (absence.id, absence.occurred_on, absence.incident, absence.justified, absence.accepted)
        for absence in found
    ] == [
        (synthetic_guid(0x7501), date(2026, 10, 14), "Falta de asistencia", False, False),
        (synthetic_guid(0x7502), date(2026, 10, 13), "Falta de asistencia", True, True),
        (synthetic_guid(0x7503), date(2026, 10, 12), "Falta de asistencia", True, False),
        (synthetic_guid(0x7504), date(2026, 10, 9), "Retraso", False, False),
    ]


async def test_reads_every_field_of_the_late_arrival(harness: Harness) -> None:
    late = (await read(harness, "Mateo"))[3]

    assert late == Absence(
        id=parse_absence_id(synthetic_guid(0x7504)),
        occurred_on=date(2026, 10, 9),
        hour="09:05",
        area="Música",
        teacher="Tomás Demo",
        incident="Retraso",
        note="Llegó con el autobús siguiente.",
        justifiable=False,
        justified=False,
        justification=None,
        accepted=False,
    )


async def test_a_child_with_no_incidents_has_no_absences(harness: Harness) -> None:
    assert await read(harness, "Lucía") == ()


async def test_each_child_has_its_own_absences(harness: Harness) -> None:
    mateo = {absence.id for absence in await read(harness, "Mateo")}
    alba = {absence.id for absence in await read(harness, "Alba")}

    assert alba == {synthetic_guid(0x7511), synthetic_guid(0x7512)}
    assert mateo.isdisjoint(alba)


async def test_opens_the_page_of_the_child_and_then_reads_the_rows(harness: Harness) -> None:
    gateway, student = harness.guardian_of("Mateo")
    await gateway.call(lambda tx: read_absences(tx, student))

    asked = [
        parse_qs(request.query)
        for request in harness.sim.requests
        if request.path == ABSENCES_GRID.page
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
    assert feed["jqGridID"] == [ABSENCES_GRID.grid_id]
    assert (feed["_search"], feed["rows"], feed["page"]) == (["false"], ["500"], ["1"])
    assert (feed["sidx"], feed["sord"]) == (["Fecha"], ["desc"])
    assert feed["nd"][0].isdecimal()


async def test_a_student_the_portal_does_not_list_is_refused_and_not_read_as_empty(
    harness: Harness, failure: Failure
) -> None:
    stranger = parse_student_id(synthetic_guid(0x999))

    detail = await failure(harness.gateway().call(lambda tx: read_absences(tx, stranger)))

    assert detail == UnexpectedReply(where="page:absences-page HTTP 500")


@pytest.mark.parametrize(
    ("options", "where"),
    [
        (SimOptions(grid_cell_count=13), "absence row 0: 13 cells instead of 14"),
        (SimOptions(grid_cell_count=15), "absence row 0: 15 cells instead of 14"),
        (SimOptions(grid_bad_date=True), "absence row 0: date"),
        (SimOptions(grid_not_json=True), "absences grid is not JSON"),
    ],
)
async def test_a_grid_the_portal_changed_is_schema_drift(
    harness: Harness, failure: Failure, options: SimOptions, where: str
) -> None:
    harness.sim.options = options
    gateway, student = harness.guardian_of("Mateo")

    detail = await failure(gateway.call(lambda tx: read_absences(tx, student)))

    assert isinstance(detail, SchemaDrift)
    assert detail.where == where
