"""The meetings of the simulated school, and the hours that its staff offers for new ones.

Like the rest of the simulator this repeats the portal's names as literals and imports nothing
from `alexia_api.portal`. Every person, date, and note here is invented.
"""

from calendar import monthrange
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from html import escape
from typing import Final

from alexia_api.sim.agenda import SimOccasion, Term
from alexia_api.sim.grids import SimGrid, resized
from alexia_api.sim.mail import list_date

GRID: Final = SimGrid(
    path="/ACWeb/paginas/Grids/Entrevistas.aspx",
    grid_id="ctl00_ctl00_ContenidoPagina_ContenidoPagina_CmptEntrevistas_gridReuniones1",
    sort="Unbound_Mes asc, Fecha",
    order="asc",
)
ICON_BASE: Final = "https://static.sim.invalid/img/entrevistas"
AGENDA_STATES: Final = frozenset({"Aceptada", "Pendiente"})
"""The states of the meetings that this simulator shows in the agenda of the guardian. The real
portal's rule is not known, and this one only keeps the simulator's two views of a meeting alike."""
INTERVIEW_MINUTES: Final = 30
_BLANK: Final = "&nbsp;"


@dataclass(frozen=True, slots=True)
class SimMeeting:
    """A meeting about one child, held on the same date every school year like an occasion."""

    id: str
    state: str
    held_on: tuple[int, int]
    """The month and the day."""
    staff: str
    requester: str
    start: str = "16:00"
    note: str = ""


@dataclass(frozen=True, slots=True)
class SimOpening:
    """Hours that a member of the staff offers on one weekday of every week. Monday is 1."""

    weekday: int
    hours: tuple[str, ...]


def _end_of(start: str) -> str:
    hour, minute = (int(part) for part in start.split(":"))
    end_hour, end_minute = divmod(hour * 60 + minute + INTERVIEW_MINUTES, 60)
    return f"{end_hour:02d}:{end_minute:02d}"


def interviews_of(meetings: Sequence[SimMeeting]) -> tuple[SimOccasion, ...]:
    """The agenda entries for the meetings that are on, half an hour each, one for each meeting."""
    return tuple(
        SimOccasion(
            id=meeting.id,
            title=f"Entrevista: {meeting.state}",
            first=meeting.held_on,
            last=meeting.held_on,
            starts=meeting.start,
            ends=_end_of(meeting.start),
        )
        for meeting in meetings
        if meeting.state in AGENDA_STATES
    )


def cells_of(
    meeting: SimMeeting, student: str, term: Term, *, date_as_iso: bool = False
) -> list[str]:
    """The twelve cells of one row. `date_as_iso` writes the date in the wrong format."""
    day = term.on(*meeting.held_on)
    state = escape(meeting.state, quote=True)
    return [
        meeting.id,
        f'<img src="{ICON_BASE}/{state.lower()}.png" alt="{state}" title="{state}" />',
        f'<img src="{ICON_BASE}/participantes.png" alt="Participantes" title="Participantes" />',
        _BLANK,
        str(day.month),
        day.isoformat() if date_as_iso else list_date(day.isoformat()),
        meeting.start,
        escape(meeting.requester),
        escape(meeting.staff),
        escape(student),
        escape(meeting.note) or _BLANK,
        _BLANK,
    ]


def rows_of(
    meetings: Sequence[SimMeeting],
    student: str,
    term: Term,
    *,
    date_as_iso: bool = False,
    cell_count: int | None = None,
) -> list[dict[str, object]]:
    """The rows of the grid, by month and then by day, as the page sorts them.

    The month comes before the year, so a school year that crosses New Year lists January first.
    """
    ordered = sorted(meetings, key=lambda meeting: meeting.held_on)
    return [
        {
            "id": meeting.id,
            "cell": resized(cells_of(meeting, student, term, date_as_iso=date_as_iso), cell_count),
        }
        for meeting in ordered
    ]


def free_hours(openings: Sequence[SimOpening], day: date, today: date) -> list[str]:
    """The hours a person offers on one day, written `15:30-16:00`. Today and the past are over."""
    if day <= today:
        return []
    return [
        hour
        for opening in openings
        if opening.weekday == day.isoweekday()
        for hour in opening.hours
    ]


def free_days(openings: Sequence[SimOpening], year: int, month: int, today: date) -> list[str]:
    """One text for each free hour of a month, written `year,month,day` with no padding."""
    entries: list[str] = []
    for number in range(1, monthrange(year, month)[1] + 1):
        free = free_hours(openings, date(year, month, number), today)
        entries.extend(f"{year},{month},{number}" for _ in free)
    return entries
