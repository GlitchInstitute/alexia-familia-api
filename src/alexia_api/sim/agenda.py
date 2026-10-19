"""The agenda of the simulated school, and the way the portal words it.

Like the rest of the simulator this repeats the portal's names as literals and imports nothing
from `alexia_api.portal`. The school year follows the simulator's clock, so a demo that runs in
any month has a term to show. Every person, title, and date here is invented.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

SimAgendaScope = Literal["child", "guardian"]

PAGE_PATH: Final = "/ACWeb/paginas/Agenda/PaginaAgenda.aspx"
FEED_PATH: Final = "/ACWeb/controladores/ControladorAgenda.ashx"
PAGE_PARAMETERS: Final = frozenset({"master", "TipoAgenda", "GuidObjeto"})
FEED_PARAMETERS: Final = frozenset({"start", "end", "_"})
MAX_SECONDS_DIGITS: Final = 11

LESSON_CLASS: Final = "evHorario"
INTERVIEW_CLASS: Final = "evEntrevista"
SCHOOL_EVENT_CLASS: Final = "evSecundario"
LESSON_OBJECT: Final = "18"
SCHOOL_EVENT_OBJECT: Final = "3"
INTERVIEW_OBJECT: Final = "47"

COUNTER_NAMES: Final = frozenset(
    {"tareas", "actividades", "anotaciones", "controles", "is_sustitucion", "pasar_lista"}
)
_BLANK_COUNTERS: Final[Mapping[str, object]] = dict.fromkeys(sorted(COUNTER_NAMES), "0")
_MADRID: Final = ZoneInfo("Europe/Madrid")
_PAGE_TYPES: Final[Mapping[SimAgendaScope, tuple[str, str]]] = {
    "child": ("3", "7"),
    "guardian": ("1", "6"),
}

LessonKey = tuple[str, str, date]
"""The person, the lesson, and the day that a change to one lesson applies to."""


@dataclass(frozen=True, slots=True)
class Term:
    """A school year, from the second week of September to the third week of July."""

    year: int

    @property
    def first(self) -> date:
        return date(self.year, 9, 8)

    @property
    def last(self) -> date:
        return date(self.year + 1, 7, 20)

    def on(self, month: int, day: int) -> date:
        """The date that an annual occasion takes in this school year."""
        return date(self.year if month >= 9 else self.year + 1, month, day)


def term_of(today: date) -> Term:
    """The school year that a day belongs to. August already belongs to the next one."""
    return Term(today.year if today.month >= 8 else today.year - 1)


@dataclass(frozen=True, slots=True)
class SimSlot:
    """A lesson of the weekly timetable. Weekdays count from Monday as 1."""

    id: str
    weekday: int
    starts: str
    ends: str
    title: str
    teacher: str


@dataclass(frozen=True, slots=True)
class SimOccasion:
    """Something the school holds on the same dates every year, such as a holiday."""

    id: str
    title: str
    first: tuple[int, int]
    last: tuple[int, int]
    starts: str = "00:00"
    ends: str = "23:59"


@dataclass(frozen=True, slots=True)
class LessonEdit:
    """A change that the school makes to one lesson on one day."""

    title: str | None = None
    teacher: str | None = None
    starts: str | None = None
    ends: str | None = None
    counters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = set(self.counters) - COUNTER_NAMES
        if unknown:
            raise ValueError(f"the portal has no counter named {sorted(unknown)}")


def page_url(scope: SimAgendaScope, person_id: str) -> str:
    """The page that opens the agenda of one person, which the feed has to come from."""
    master, agenda_type = _PAGE_TYPES[scope]
    return f"{PAGE_PATH}?master={master}&TipoAgenda={agenda_type}&GuidObjeto={person_id}"


def page_target(
    query: Mapping[str, str], children: Collection[str], guardian: str
) -> tuple[SimAgendaScope, str] | None:
    """Whose agenda a page request opens, or None when the portal would not serve the request."""
    if set(query) != PAGE_PARAMETERS:
        return None
    person = query["GuidObjeto"]
    asked = (query["master"], query["TipoAgenda"])
    if asked == _PAGE_TYPES["child"] and person in children:
        return ("child", person)
    if asked == _PAGE_TYPES["guardian"] and person == guardian:
        return ("guardian", person)
    return None


def feed_seconds(query: Mapping[str, str]) -> tuple[int, int] | None:
    """The range a feed request asks for, or None when the portal would not serve the request."""
    if set(query) != FEED_PARAMETERS or not query["_"].isdecimal():
        return None
    start, end = query["start"], query["end"]
    if not all(text.isdecimal() and len(text) <= MAX_SECONDS_DIGITS for text in (start, end)):
        return None
    return int(start), int(end)


def asked_days(start: int, end: int) -> tuple[date, date]:
    """The first and the last local day that the seconds of a feed request touch."""
    first = _local_date(start)
    return first, max(first, _local_date(end - 1))


def _local_date(seconds: int) -> date:
    return datetime.fromtimestamp(seconds, _MADRID).date()


def stamp(day: date, clock_time: str) -> str:
    """Local wall time with a Z on the end, which is how the portal writes it."""
    return f"{day.isoformat()}T{clock_time}:00Z"


def feed_entry(
    *,
    entry_id: str,
    title: str,
    start: str,
    end: str,
    class_name: str,
    object_type: str,
    object_guid: str,
    teacher: str = "",
    counters: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """One entry of the agenda feed, with every field the portal sends."""
    return {
        "title": title,
        "id": entry_id,
        "start": start,
        "end": end,
        "className": class_name,
        "editable": False,
        "color": "#336699",
        "objetoTipo": object_type,
        "objetoGuid": object_guid,
        "progreso": "0",
        "is_pd": "0",
        **_BLANK_COUNTERS,
        **(counters or {}),
        "seccion": teacher,
        "size": "",
        "aplicarEstilo": True,
    }


def lessons_between(
    first: date,
    last: date,
    term: Term,
    person_id: str,
    timetable: Sequence[SimSlot],
    *,
    edits: Mapping[LessonKey, LessonEdit],
    cancelled: Collection[LessonKey],
    object_guid: str,
) -> list[dict[str, object]]:
    """The lessons of every school day from `first` to `last`, kept inside the term."""
    begin, finish = max(first, term.first), min(last, term.last)
    entries: list[dict[str, object]] = []
    for offset in range((finish - begin).days + 1):
        day = begin + timedelta(days=offset)
        for slot in timetable:
            key = (person_id, slot.id, day)
            if slot.weekday != day.isoweekday() or key in cancelled:
                continue
            edit = edits.get(key, LessonEdit())
            entries.append(
                feed_entry(
                    entry_id=slot.id,
                    title=edit.title or slot.title,
                    start=stamp(day, edit.starts or slot.starts),
                    end=stamp(day, edit.ends or slot.ends),
                    class_name=LESSON_CLASS,
                    object_type=LESSON_OBJECT,
                    object_guid=object_guid,
                    teacher=edit.teacher or slot.teacher,
                    counters=edit.counters,
                )
            )
    return entries


def occasions_in(
    occasions: Sequence[SimOccasion],
    term: Term,
    *,
    class_name: str,
    object_type: str,
    object_guid: str,
    window: tuple[date, date] | None,
) -> list[dict[str, object]]:
    """The occasions of a term, all of them without a window, else the ones that touch it."""
    entries: list[dict[str, object]] = []
    for occasion in occasions:
        first, last = term.on(*occasion.first), term.on(*occasion.last)
        if window is not None and not (first <= window[1] and last >= window[0]):
            continue
        entries.append(
            feed_entry(
                entry_id=occasion.id,
                title=occasion.title,
                start=stamp(first, occasion.starts),
                end=stamp(last, occasion.ends),
                class_name=class_name,
                object_type=object_type,
                object_guid=object_guid,
            )
        )
    return entries
