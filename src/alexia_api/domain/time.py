"""Calendar and clock rules for the portal.

The portal speaks in local school time and never says so. Lists print dates as dd/mm/yyyy. The
agenda feed prints ISO strings that end in Z even though the numbers are local wall time. Every
function here names the zone a value belongs to, so the wrong Z never reaches the API.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_ZONE_NAME = "Europe/Madrid"

_LIST_DATE = re.compile(r"([0-9]{2})/([0-9]{2})/([0-9]{4})")
_FEED_TIME = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2})(?::[0-9]{2}(?:\.[0-9]+)?)?Z?"
)
_LAST_SECOND = time(23, 59, 59)


class UnknownZoneError(ValueError):
    """A configured time zone name that the tz database does not know."""


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise UnknownZoneError(f"unknown time zone: {name!r}") from error


def portal_list_date(text: str) -> date | None:
    """Read a list date written dd/mm/yyyy. Anything else, including 31/02/2026, gives None."""
    match = _LIST_DATE.fullmatch(text.strip())
    if match is None:
        return None
    day, month, year = (int(group) for group in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def wall_of(text: str) -> datetime | None:
    """Read an agenda feed time as naive local wall time. A trailing Z is accepted and ignored."""
    match = _FEED_TIME.fullmatch(text.strip())
    if match is None:
        return None
    year, month, day, hour, minute = (int(group) for group in match.groups())
    try:
        return datetime(year, month, day, hour, minute)  # noqa: DTZ001
    except ValueError:
        return None


def instant_of(wall: datetime, tz: ZoneInfo) -> datetime:
    """Place a local wall time in a zone and return the real instant in that zone.

    A wall time that happens twice, when clocks go back, takes the first occurrence. A wall time
    that never happens, when clocks go forward, lands one hour later.
    """
    if wall.tzinfo is not None:
        raise ValueError("a wall time carries no zone")
    return wall.replace(tzinfo=tz).astimezone(UTC).astimezone(tz)


def midnight_seconds(day: date, tz: ZoneInfo) -> int:
    """Unix seconds at the start of a local day. The agenda feed filters on these."""
    return int(instant_of(datetime.combine(day, time.min), tz).timestamp())


@dataclass(frozen=True, slots=True)
class DateWindow:
    """An inclusive range of local days."""

    first: date
    last: date

    def days(self) -> list[date]:
        count = (self.last - self.first).days + 1
        return [self.first + timedelta(days=offset) for offset in range(max(count, 0))]

    def overlaps(self, starts: datetime, ends: datetime) -> bool:
        window_start = datetime.combine(self.first, time.min)
        window_end = datetime.combine(self.last, _LAST_SECOND)
        return ends >= window_start and starts <= window_end


def window_around(today: date, back: int, ahead: int) -> DateWindow:
    return DateWindow(first=today - timedelta(days=back), last=today + timedelta(days=ahead))
