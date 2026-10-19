"""Reading the absences of a child. The portal serves them as a grid with fourteen cells per row.

The cells, from the first, hold the id, an image that marks an incident that cannot be justified,
the date, a value, the month, the hour, the student, the area, the teacher, the incident, a note,
whether it was justified, the reason, and a box for whether the school accepted it. The shapes of
the cells come from the page's script and from a simulator. No row of a real list has been seen.
"""

from typing import Final

from selectolax.lexbor import LexborHTMLParser

from alexia_api.domain.absences import Absence
from alexia_api.domain.ids import AbsenceId, InvalidIdError, StudentId, parse_absence_id
from alexia_api.domain.time import portal_list_date
from alexia_api.portal.grid import (
    GridRow,
    GridSpec,
    cell_flag,
    cell_text,
    parse_grid_json,
    read_grid_text,
    row_drift,
    text_cells,
)
from alexia_api.portal.session import Tx

ABSENCE_CELLS: Final = 14
ABSENCES_GRID: Final = GridSpec(
    name="absences",
    page="/ACWeb/paginas/incidencias/Justificar.aspx",
    grid_id="ctl00_ctl00_ContenidoPagina_ContenidoPagina_CmptIncidencias_gridJustificar",
    sort="Fecha",
    order="desc",
)


def _absence_id(text: str) -> AbsenceId | None:
    try:
        return parse_absence_id(text)
    except InvalidIdError:
        return None


def parse_absence_row(row: GridRow, index: int, page_text: str) -> Absence:
    cells = text_cells(row, what="absence", index=index, count=ABSENCE_CELLS, page_text=page_text)
    absence_id = _absence_id(cells[0])
    if absence_id is None or absence_id != _absence_id(row.id):
        raise row_drift("absence", index, "the row id and the first cell disagree", page_text)
    occurred_on = portal_list_date(cell_text(cells[2]))
    if occurred_on is None:
        raise row_drift("absence", index, "date", page_text)

    return Absence(
        id=absence_id,
        occurred_on=occurred_on,
        hour=cell_text(cells[5]) or None,
        area=cell_text(cells[7]) or None,
        teacher=cell_text(cells[8]) or None,
        incident=cell_text(cells[9]),
        note=cell_text(cells[10]) or None,
        justifiable=LexborHTMLParser(cells[1]).css_first("img") is None,
        justified=cell_flag(cells[11]),
        justification=cell_text(cells[12]) or None,
        accepted=cell_flag(cells[13]),
    )


def parse_absences(text: str) -> tuple[Absence, ...]:
    grid = parse_grid_json(text, "absences grid")
    return tuple(parse_absence_row(row, index, text) for index, row in enumerate(grid.rows))


async def read_absences(tx: Tx, student: StudentId) -> tuple[Absence, ...]:
    """Open the absences of one child and read every row, newest first."""
    return parse_absences(await read_grid_text(tx, ABSENCES_GRID, student))
