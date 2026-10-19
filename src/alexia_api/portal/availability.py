"""Reading the days and hours that a member of the staff offers for a meeting.

Two script services answer. The first lists the free hours of a month as texts written
`year,month,day` with no padding, one text for each free hour, so a day with three free hours
appears three times. The second lists the free hours of one day as texts written `15:30-16:00`.
A person with nothing free answers an empty object. Both calls only read.
"""

import json
import re
from datetime import date, datetime, time
from typing import Final
from zoneinfo import ZoneInfo

from alexia_api.domain.errors import PortalError, SchemaDrift, sample_of
from alexia_api.domain.ids import StaffId
from alexia_api.domain.meetings import AvailableSlot
from alexia_api.domain.time import instant_of
from alexia_api.portal import wire
from alexia_api.portal.allowlist import GET_AVAILABLE_DAYS, GET_AVAILABLE_HOURS
from alexia_api.portal.session import Tx
from alexia_api.portal.ws import call_ws

_DAY_ENTRY: Final = re.compile(r"([0-9]{4}),([0-9]{1,2}),([0-9]{1,2})")
_HOURS_ENTRY: Final = re.compile(r"([0-9]{1,2}):([0-9]{2})-([0-9]{1,2}):([0-9]{2})")


def _drift(where: str, entries: list[str]) -> PortalError:
    return PortalError(SchemaDrift(where=where, sample=sample_of(json.dumps(entries))))


def parse_available_days(entries: list[str]) -> tuple[date, ...]:
    """The distinct days that have a free hour, earliest first."""
    days: set[date] = set()
    for entry in entries:
        found = _DAY_ENTRY.fullmatch(entry.strip())
        if found is None:
            raise _drift("availability days", entries)
        year, month, day = (int(group) for group in found.groups())
        try:
            days.add(date(year, month, day))
        except ValueError:
            raise _drift("availability days", entries) from None
    return tuple(sorted(days))


def _span_of(entry: str) -> tuple[time, time] | None:
    found = _HOURS_ENTRY.fullmatch(entry.strip())
    if found is None:
        return None
    first_hour, first_minute, last_hour, last_minute = (int(group) for group in found.groups())
    try:
        span = (time(first_hour, first_minute), time(last_hour, last_minute))
    except ValueError:
        return None
    return span if span[0] < span[1] else None


def parse_available_hours(
    entries: list[str], day: date, zone: ZoneInfo
) -> tuple[AvailableSlot, ...]:
    """The distinct free slots of one day, earliest first."""
    spans: set[tuple[time, time]] = set()
    for entry in entries:
        span = _span_of(entry)
        if span is None:
            raise _drift("availability hours", entries)
        spans.add(span)
    return tuple(
        AvailableSlot(
            starts_at=instant_of(datetime.combine(day, start), zone),
            ends_at=instant_of(datetime.combine(day, end), zone),
        )
        for start, end in sorted(spans)
    )


async def read_available_days(tx: Tx, staff: StaffId, year: int, month: int) -> tuple[date, ...]:
    """The days of a month on which a person has at least one free hour."""
    reply = await call_ws(
        tx, GET_AVAILABLE_DAYS, wire.AvailableDaysParams(staff_id=staff, month=month, year=year)
    )
    return parse_available_days(reply.entries or [])


async def read_available_hours(tx: Tx, staff: StaffId, day: date) -> tuple[AvailableSlot, ...]:
    """The free slots of a person on one day."""
    reply = await call_ws(
        tx, GET_AVAILABLE_HOURS, wire.AvailableHoursParams(staff_id=staff, day=day)
    )
    return parse_available_hours(reply.hours or [], day, tx.zone)
