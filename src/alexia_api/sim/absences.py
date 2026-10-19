"""The absences of the simulated school, and the way the portal words them.

Like the rest of the simulator this repeats the portal's names as literals and imports nothing
from `alexia_api.portal`. Every date, name, and note here is invented.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from typing import Final

from alexia_api.sim.grids import SimGrid, checkbox, resized
from alexia_api.sim.mail import list_date

GRID: Final = SimGrid(
    path="/ACWeb/paginas/incidencias/Justificar.aspx",
    grid_id="ctl00_ctl00_ContenidoPagina_ContenidoPagina_CmptIncidencias_gridJustificar",
    sort="Fecha",
    order="desc",
)
ICON_BASE: Final = "https://static.sim.invalid/img/incidencias"
_BLANK: Final = "&nbsp;"


@dataclass(frozen=True, slots=True)
class SimAbsence:
    id: str
    date: str
    incident: str
    hour: str = ""
    area: str = "Tutoría"
    teacher: str = ""
    note: str = ""
    justifiable: bool = True
    justified: bool = False
    justification: str = ""
    accepted: bool = False


def cells_of(absence: SimAbsence, student: str, *, date_as_iso: bool = False) -> list[str]:
    """The fourteen cells of one row. `date_as_iso` writes the date in the wrong format."""
    _, month, _ = absence.date.split("-")
    marked = (
        f'<img src="{ICON_BASE}/no_justificable.png" alt="No justificable" '
        'title="No justificable" />'
    )
    return [
        absence.id,
        _BLANK if absence.justifiable else marked,
        absence.date if date_as_iso else list_date(absence.date),
        "",
        str(int(month)),
        escape(absence.hour) or _BLANK,
        escape(student),
        escape(absence.area),
        escape(absence.teacher),
        escape(absence.incident),
        escape(absence.note) or _BLANK,
        "Sí" if absence.justified else "No",
        escape(absence.justification) or _BLANK,
        checkbox(absence.accepted),
    ]


def rows_of(
    absences: Sequence[SimAbsence],
    student: str,
    *,
    date_as_iso: bool = False,
    cell_count: int | None = None,
) -> list[dict[str, object]]:
    """The rows of the grid, newest day first, as the page sorts them."""
    newest = sorted(absences, key=lambda absence: absence.date, reverse=True)
    return [
        {
            "id": absence.id,
            "cell": resized(cells_of(absence, student, date_as_iso=date_as_iso), cell_count),
        }
        for absence in newest
    ]
