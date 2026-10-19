"""The agenda as an iCalendar file, for a calendar app that subscribes to a URL.

Each entry becomes one event. A timed entry is one instant written in UTC, so a calendar app
needs no rules of the school's time zone to place it, and a lesson at nine stays at nine on both
sides of a clock change. Apps differ in how well they read zone rules from a file, and a misread
puts every summer lesson an hour off. The zone decides which day an all-day entry falls on and is
named as the home zone of the calendar. The zone and the time of the stamp are passed in, and
nothing here reads the system's clock.

Every word the school wrote is cleaned before it goes into the file. A title can hold a line
break, a control character, or a character that reverses the text, and none of them may change
what a calendar app shows or break the file.
"""

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event, vText

from alexia_api.domain.agenda import AgendaEvent, EventKind

MEDIA_TYPE: Final = "text/calendar; charset=utf-8"
PRODUCT_ID: Final = "-//alexia-familia-api//School calendar//EN"
UID_DOMAIN: Final = "alexia-familia-api"
REFRESH_EVERY: Final = timedelta(hours=1)
UNNAMED: Final = "School calendar"

_LINE_BREAKS: Final = frozenset({"Cc", "Zl", "Zp"})
_INVISIBLE: Final = frozenset({"Cf", "Cs"})

type _Occasion = tuple[EventKind, str, datetime, datetime]


@dataclass(frozen=True, slots=True)
class CalendarSource:
    """The entries of one person, and what tells them from the entries of another person."""

    scope: str
    label: str | None
    events: tuple[AgendaEvent, ...]


@dataclass(frozen=True, slots=True)
class CalendarEntry:
    """One entry of a file, with the scope that keeps its id apart from other people's."""

    event: AgendaEvent
    scope: str
    label: str | None


def plain(text: str) -> str:
    """The text as one line, without control or invisible characters and with single spaces.

    A character that reverses the direction of text can make one title read as another, so those
    go with the rest.
    """
    shown = "".join(
        " " if unicodedata.category(char) in _LINE_BREAKS else char
        for char in text
        if unicodedata.category(char) not in _INVISIBLE
    )
    return " ".join(shown.split())


def _joined(parts: list[str]) -> str:
    return ", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]


def describe(event: AgendaEvent) -> str | None:
    """What a lesson's teacher and flags say, in plain sentences.

    Any other entry has nothing to add to its title. The portal does not say whom `teacher` names
    on an interview or a school event, so those do not claim it is a teacher.
    """
    if event.kind != "lesson":
        return None
    lines = []
    teacher = plain(event.teacher) if event.teacher else ""
    if teacher:
        lines.append(f"Teacher {teacher}.")
    signals = event.signals
    if signals is not None:
        flagged = [
            f"{count} {one if count == 1 else many}"
            for count, one, many in (
                (signals.tasks, "task", "tasks"),
                (signals.activities, "activity", "activities"),
                (signals.notes, "note", "notes"),
                (signals.tests, "test", "tests"),
            )
            if count > 0
        ]
        if flagged:
            lines.append(f"The school flagged {_joined(flagged)}.")
        if signals.substitution:
            lines.append("A substitute teacher takes this lesson.")
    return "\n".join(lines) or None


def _occasion(event: AgendaEvent) -> _Occasion:
    return event.kind, event.title, event.starts_at, event.ends_at


def calendar_entries(sources: Sequence[CalendarSource], *, shared: str) -> list[CalendarEntry]:
    """The entries of several people as one list, with an occasion that two people share once.

    A lesson belongs to the person who attends it, even when two people have the same lesson.
    Any other entry that has the same kind, title, and times for more than one person is one
    occasion, such as a holiday of the whole school. It appears once, under the `shared` scope
    and with no label. The first person to hold it decides which id it keeps.
    """
    holders: dict[_Occasion, set[str]] = {}
    for source in sources:
        for event in source.events:
            holders.setdefault(_occasion(event), set()).add(source.scope)
    entries: list[CalendarEntry] = []
    written: set[_Occasion] = set()
    for source in sources:
        for event in source.events:
            occasion = _occasion(event)
            if event.kind == "lesson" or len(holders[occasion]) == 1:
                entries.append(CalendarEntry(event, source.scope, source.label))
            elif occasion not in written:
                written.add(occasion)
                entries.append(CalendarEntry(event, shared, None))
    return entries


def _uid(entry: CalendarEntry) -> str:
    named = "".join(char for char in f"{entry.scope}.{entry.event.id}" if char.isprintable())
    return f"{named.replace(' ', '_')}@{UID_DOMAIN}"


def _summary(entry: CalendarEntry) -> str:
    title = plain(entry.event.title)
    label = plain(entry.label) if entry.label else ""
    return f"{label}: {title}" if label and title else label or title


def _vevent(entry: CalendarEntry, zone: ZoneInfo, stamped_at: datetime) -> Event:
    event = entry.event
    item = Event()
    item.add("uid", _uid(entry))
    item.add("dtstamp", stamped_at.astimezone(UTC))
    item.add("summary", _summary(entry))
    if event.all_day:
        first = event.starts_at.astimezone(zone).date()
        last = max(first, event.ends_at.astimezone(zone).date())
        item.add("dtstart", first)
        item.add("dtend", last + timedelta(days=1))
        item.add("transp", "TRANSPARENT")
    else:
        item.add("dtstart", event.starts_at.astimezone(UTC))
        if event.ends_at > event.starts_at:
            item.add("dtend", event.ends_at.astimezone(UTC))
    description = describe(event)
    if description:
        item.add("description", description)
    return item


def render_calendar(
    name: str, entries: Iterable[CalendarEntry], *, zone: ZoneInfo, stamped_at: datetime
) -> bytes:
    """The file for a list of entries, with its lines ended by CRLF as the standard asks."""
    calendar = Calendar()
    calendar.add("prodid", PRODUCT_ID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", vText(plain(name) or UNNAMED))
    calendar.add("x-wr-timezone", zone.key)
    calendar.add("refresh-interval", REFRESH_EVERY, parameters={"VALUE": "DURATION"})
    calendar.add("x-published-ttl", "PT1H")
    ordered = sorted(
        entries, key=lambda entry: (entry.event.starts_at, entry.scope, entry.event.id)
    )
    for entry in ordered:
        calendar.add_component(_vevent(entry, zone, stamped_at))
    data: bytes = calendar.to_ical()
    return data
