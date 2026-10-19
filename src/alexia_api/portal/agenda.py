"""Reading the agenda, which is the school's calendar for one child or for the guardian.

The portal builds the agenda in two steps. A page opens the agenda of one person, which makes
the server remember whose agenda is open, and then a feed answers with the entries of a date
range. The feed has to come after the page, and it ignores the end of its range, so the reader
asks for a range and then keeps only the entries that fall inside it.
"""

import json
import math
import unicodedata
from collections.abc import Mapping
from datetime import datetime, time, timedelta
from typing import Final
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter, ValidationError

from alexia_api.domain.agenda import AgendaEvent, AgendaScope, EventKind, LessonSignals
from alexia_api.domain.errors import PortalError, SchemaDrift, SessionExpired, sample_of
from alexia_api.domain.ids import PersonId
from alexia_api.domain.time import DateWindow, instant_of, midnight_seconds, wall_of
from alexia_api.portal.pages import FEED_ACCEPT, PAGE_ACCEPT, PageRequest, get_page
from alexia_api.portal.session import Tx
from alexia_api.portal.wire import FeedEvent, Flag
from alexia_api.portal.ws import HOME_PATH, looks_like_logon_page

AGENDA_PAGE: Final = "/ACWeb/paginas/Agenda/PaginaAgenda.aspx"
AGENDA_FEED: Final = "/ACWeb/controladores/ControladorAgenda.ashx"

LESSON_CLASS: Final = "evHorario"
INTERVIEW_CLASS: Final = "evEntrevista"
SCHOOL_EVENT_CLASS: Final = "evSecundario"
HOLIDAY_TITLE: Final = "festivo"

_MASTER_AND_TYPE: Final[Mapping[AgendaScope, tuple[str, str]]] = {
    "child": ("3", "7"),
    "guardian": ("1", "6"),
}
_MIDNIGHT: Final = time(0, 0)
_LAST_MINUTE: Final = time(23, 59)
_FEED = TypeAdapter(list[FeedEvent])


def agenda_page_path(scope: AgendaScope, person: PersonId) -> str:
    master, agenda_type = _MASTER_AND_TYPE[scope]
    query = urlencode({"master": master, "TipoAgenda": agenda_type, "GuidObjeto": person})
    return f"{AGENDA_PAGE}?{query}"


def agenda_feed_path(window: DateWindow, asked_at: datetime, zone: ZoneInfo) -> str:
    """The range is in Unix seconds and the last number is the browser's cache buster."""
    query = {
        "start": midnight_seconds(window.first, zone),
        "end": midnight_seconds(window.last + timedelta(days=1), zone),
        "_": int(asked_at.timestamp() * 1000),
    }
    return f"{AGENDA_FEED}?{urlencode(query)}"


def counter_of(value: Flag) -> int:
    """Read a counter that the portal writes as text, as a number, or as a boolean.

    A zero, a false, and an empty text mean that nothing is flagged. Any other value means that
    something is, and a number says how many. A value that is not understood counts as one,
    because a flag that the school raised must not vanish.
    """
    match value:
        case None | False:
            return 0
        case True:
            return 1
        case int():
            return max(value, 0)
        case float():
            return _count_of_number(value)
        case str():
            return _count_in(value)


def _count_of_number(number: float) -> int:
    if not math.isfinite(number):
        return 1
    return max(math.ceil(number), 0)


def _count_in(text: str) -> int:
    word = text.strip().lower()
    if word in {"", "false"}:
        return 0
    try:
        return _count_of_number(float(word))
    except ValueError:
        return 1


def normalized(title: str) -> str:
    """Lower-case letters and digits only, without accents and with single spaces."""
    decomposed = unicodedata.normalize("NFKD", title)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    words = "".join(char if char.isalnum() else " " for char in plain.lower())
    return " ".join(words.split())


def kind_of(class_name: str, title: str) -> EventKind:
    if class_name == LESSON_CLASS:
        return "lesson"
    if class_name == INTERVIEW_CLASS:
        return "interview"
    if class_name == SCHOOL_EVENT_CLASS and normalized(title) == HOLIDAY_TITLE:
        return "holiday"
    return "school_event"


def _signals_of(item: FeedEvent) -> LessonSignals:
    return LessonSignals(
        tasks=counter_of(item.tasks),
        activities=counter_of(item.activities),
        notes=counter_of(item.notes),
        tests=counter_of(item.tests),
        substitution=counter_of(item.substitution) > 0,
    )


def _event_of(item: FeedEvent, starts: datetime, ends: datetime, zone: ZoneInfo) -> AgendaEvent:
    kind = kind_of(item.class_name, item.title)
    return AgendaEvent(
        id=f"{item.id}|{starts.date().isoformat()}",
        kind=kind,
        title=item.title.strip(),
        teacher=(item.teacher or "").strip() or None,
        starts_at=instant_of(starts, zone),
        ends_at=instant_of(ends, zone),
        all_day=starts.time() == _MIDNIGHT and ends.time() in {_MIDNIGHT, _LAST_MINUTE},
        signals=_signals_of(item) if kind == "lesson" else None,
    )


def events_in(
    items: list[FeedEvent], window: DateWindow, zone: ZoneInfo
) -> tuple[AgendaEvent, ...]:
    """Keep the entries that touch the window, once each, in the order they happen."""
    found: dict[str, AgendaEvent] = {}
    for item in items:
        starts, ends = wall_of(item.start), wall_of(item.end)
        if starts is None or ends is None or not window.overlaps(starts, ends):
            continue
        event = _event_of(item, starts, ends, zone)
        found.setdefault(event.id, event)
    return tuple(sorted(found.values(), key=lambda event: (event.starts_at, event.id)))


def parse_feed(text: str) -> list[FeedEvent]:
    try:
        payload = json.loads(text)
    except ValueError:
        if looks_like_logon_page(text):
            raise PortalError(SessionExpired()) from None
        raise PortalError(
            SchemaDrift(where="agenda feed is not JSON", sample=sample_of(text))
        ) from None
    try:
        return _FEED.validate_python(payload)
    except ValidationError as error:
        raise PortalError(SchemaDrift(where="agenda feed", sample=sample_of(text))) from error


async def read_agenda(
    tx: Tx, scope: AgendaScope, person: PersonId, window: DateWindow
) -> tuple[AgendaEvent, ...]:
    """Open the agenda of one person and read the entries of a range of days."""
    page = agenda_page_path(scope, person)
    await get_page(
        tx,
        PageRequest(name="agenda", path=page, referer=tx.absolute(HOME_PATH), accept=PAGE_ACCEPT),
    )
    feed = await get_page(
        tx,
        PageRequest(
            name="agenda-feed",
            path=agenda_feed_path(window, tx.now(), tx.zone),
            referer=tx.absolute(page),
            accept=FEED_ACCEPT,
            xhr=True,
        ),
    )
    return events_in(parse_feed(feed.text()), window, tx.zone)
