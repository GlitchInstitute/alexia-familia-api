"""Reading the meetings of a child. The portal serves them as a grid with twelve cells per row.

The cells, from the first, hold the id, an icon whose title is the state, an icon for the people
who take part, the time that remains, the month, the date, the start time, who asked for the
meeting, who is responsible for it, the child and class, the notes, and a small file icon. The
state word `Aceptada` and the shapes of these cells were seen once, on a real list. The other
state words are a reader's guess, so a label that matches none of them reads as `unknown`.
"""

import re
from datetime import datetime, time
from typing import Final
from zoneinfo import ZoneInfo

from selectolax.lexbor import LexborHTMLParser

from alexia_api.domain.ids import InvalidIdError, MeetingId, StudentId, parse_meeting_id
from alexia_api.domain.meetings import Meeting, MeetingState
from alexia_api.domain.time import instant_of, portal_list_date
from alexia_api.portal.grid import (
    GridRow,
    GridSpec,
    cell_text,
    parse_grid_json,
    read_grid_text,
    row_drift,
    text_cells,
)
from alexia_api.portal.session import Tx

MEETING_CELLS: Final = 12
MEETINGS_GRID: Final = GridSpec(
    name="meetings",
    page="/ACWeb/paginas/Grids/Entrevistas.aspx",
    grid_id="ctl00_ctl00_ContenidoPagina_ContenidoPagina_CmptEntrevistas_gridReuniones1",
    sort="Unbound_Mes asc, Fecha",
    order="asc",
)

_STATE_WORDS: Final[tuple[tuple[re.Pattern[str], MeetingState], ...]] = (
    (re.compile(r"cancelad|anulad"), "cancelled"),
    (re.compile(r"rechazad|denegad"), "declined"),
    (re.compile(r"aceptad|confirmad"), "accepted"),
    (re.compile(r"realizad|celebrad"), "done"),
    (re.compile(r"solicitad|pendiente|propuest"), "requested"),
)
_START_TIME: Final = re.compile(r"([0-9]{1,2}):([0-9]{2})")


def state_of(label: str) -> MeetingState:
    """Name the state that a label of the portal tells.

    A label that has the words of more than one state is read as the first of these that it has.
    The order is cancelled, declined, accepted, done, and requested, so a cancelled meeting never
    reads as one that is still on.
    """
    lowered = label.lower()
    for pattern, state in _STATE_WORDS:
        if pattern.search(lowered):
            return state
    return "unknown"


def _label_of(cell: str) -> str:
    """The state is the title of the cell's icon. A cell with words and no icon is read as words."""
    icon = LexborHTMLParser(cell).css_first("[title]")
    title = icon.attributes.get("title") if icon is not None else None
    return " ".join((title or cell_text(cell)).split())


def _meeting_id(text: str) -> MeetingId | None:
    try:
        return parse_meeting_id(text)
    except InvalidIdError:
        return None


def _start_of(text: str) -> time | None:
    found = _START_TIME.fullmatch(text)
    if found is None:
        return None
    try:
        return time(int(found.group(1)), int(found.group(2)))
    except ValueError:
        return None


def parse_meeting_row(row: GridRow, index: int, page_text: str, zone: ZoneInfo) -> Meeting:
    cells = text_cells(row, what="meeting", index=index, count=MEETING_CELLS, page_text=page_text)
    meeting_id = _meeting_id(cells[0])
    if meeting_id is None or meeting_id != _meeting_id(row.id):
        raise row_drift("meeting", index, "the row id and the first cell disagree", page_text)
    day = portal_list_date(cell_text(cells[5]))
    if day is None:
        raise row_drift("meeting", index, "date", page_text)
    start = _start_of(cell_text(cells[6]))
    if start is None:
        raise row_drift("meeting", index, "start time", page_text)

    label = _label_of(cells[1])
    return Meeting(
        id=meeting_id,
        state=state_of(label),
        state_label=label,
        starts_at=instant_of(datetime.combine(day, start), zone),
        requested_by=cell_text(cells[7]) or None,
        staff=cell_text(cells[8]) or None,
        note=cell_text(cells[10]) or None,
    )


def parse_meetings(text: str, zone: ZoneInfo) -> tuple[Meeting, ...]:
    """Read the rows of a grid answer, in the order the meetings take place."""
    grid = parse_grid_json(text, "meetings grid")
    meetings = (parse_meeting_row(row, index, text, zone) for index, row in enumerate(grid.rows))
    return tuple(sorted(meetings, key=lambda meeting: (meeting.starts_at, meeting.id)))


async def read_meetings(tx: Tx, student: StudentId) -> tuple[Meeting, ...]:
    """Open the meetings of one child and read every row, oldest first."""
    return parse_meetings(await read_grid_text(tx, MEETINGS_GRID, student), tx.zone)
