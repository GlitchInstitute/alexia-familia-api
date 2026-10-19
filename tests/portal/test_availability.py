"""Reading the days and hours that a member of the staff offers for a meeting."""

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from alexia_api.domain.errors import PortalError, SchemaDrift, WsRejected
from alexia_api.domain.ids import StaffId, parse_staff_id
from alexia_api.domain.meetings import AvailableSlot
from alexia_api.portal import wire
from alexia_api.portal.allowlist import GET_AVAILABLE_DAYS
from alexia_api.portal.availability import (
    parse_available_days,
    parse_available_hours,
    read_available_days,
    read_available_hours,
)
from alexia_api.portal.session import Tx
from alexia_api.portal.ws import call_ws
from alexia_api.sim.app import SimOptions
from alexia_api.sim.world import synthetic_guid
from tests.harness import Failure, Harness

MADRID = ZoneInfo("Europe/Madrid")
BOGOTA = ZoneInfo("America/Bogota")
DAY = date(2026, 1, 6)
TUTOR_A = parse_staff_id(synthetic_guid(0x601))
TUTOR_B = parse_staff_id(synthetic_guid(0x603))
MUSIC = parse_staff_id(synthetic_guid(0x604))
STRANGER = parse_staff_id(synthetic_guid(0x999))


def slot(
    day: int, start: tuple[int, int], end: tuple[int, int], zone: ZoneInfo = MADRID
) -> AvailableSlot:
    return AvailableSlot(
        starts_at=datetime(2026, 1, day, *start, tzinfo=zone),
        ends_at=datetime(2026, 1, day, *end, tzinfo=zone),
    )


def drift_of(where: str, entries: list[str]) -> SchemaDrift:
    return SchemaDrift(where=where, sample=json.dumps(entries))


def test_a_day_with_several_free_hours_is_one_day() -> None:
    entries = ["2026,1,6", "2026,1,6", "2026,1,8", "2026,1,6"]

    assert parse_available_days(entries) == (date(2026, 1, 6), date(2026, 1, 8))


def test_days_are_listed_earliest_first_whatever_order_the_portal_used() -> None:
    entries = ["2026,2,3", "2026,1,29", "2026,1,6", "2025,12,30"]

    assert parse_available_days(entries) == (
        date(2025, 12, 30),
        date(2026, 1, 6),
        date(2026, 1, 29),
        date(2026, 2, 3),
    )


def test_no_entries_are_no_days() -> None:
    assert parse_available_days([]) == ()


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ("2026,1,6", date(2026, 1, 6)),
        ("2026,01,06", date(2026, 1, 6)),
        (" 2026,1,6 ", date(2026, 1, 6)),
        ("2026,12,31", date(2026, 12, 31)),
        ("2028,2,29", date(2028, 2, 29)),
    ],
)
def test_a_day_is_written_year_month_day_with_or_without_padding(
    entry: str, expected: date
) -> None:
    assert parse_available_days([entry]) == (expected,)


@pytest.mark.parametrize(
    "entry",
    [
        "2026-01-06",
        "2026,13,1",
        "2026,0,5",
        "2026,2,30",
        "2027,2,29",
        "26,1,6",
        "2026,1",
        "2026,1,6,3",
        "2026,1,6x",
        "",
        "tomorrow",
    ],
)
def test_a_day_the_portal_writes_another_way_is_schema_drift(entry: str) -> None:
    entries = ["2026,1,6", entry]

    with pytest.raises(PortalError) as raised:
        parse_available_days(entries)

    assert raised.value.detail == drift_of("availability days", entries)


def test_hours_are_slots_of_the_day_in_the_zone_of_the_school() -> None:
    found = parse_available_hours(["15:30-16:00", "16:00-16:30"], DAY, MADRID)

    assert found == (slot(6, (15, 30), (16, 0)), slot(6, (16, 0), (16, 30)))
    assert found[0].starts_at.utcoffset() == timedelta(hours=1)


def test_hours_are_placed_in_the_zone_they_are_read_in() -> None:
    (found,) = parse_available_hours(["15:30-16:00"], DAY, BOGOTA)

    assert found == slot(6, (15, 30), (16, 0), BOGOTA)
    assert found.starts_at.utcoffset() == timedelta(hours=-5)


def test_hours_are_earliest_first_and_each_slot_is_listed_once() -> None:
    entries = ["16:00-16:30", "9:05-9:35", "16:00-16:30", "15:30-16:00"]

    assert parse_available_hours(entries, DAY, MADRID) == (
        slot(6, (9, 5), (9, 35)),
        slot(6, (15, 30), (16, 0)),
        slot(6, (16, 0), (16, 30)),
    )


def test_a_slot_may_be_wrapped_in_spaces() -> None:
    assert parse_available_hours([" 15:30-16:00 "], DAY, MADRID) == (slot(6, (15, 30), (16, 0)),)


def test_no_entries_are_no_hours() -> None:
    assert parse_available_hours([], DAY, MADRID) == ()


@pytest.mark.parametrize(
    "entry",
    [
        "15:30",
        "16:00-15:30",
        "15:30-15:30",
        "25:00-26:00",
        "15:60-16:00",
        "15:30-16:0",
        "15:30-16:00-17:00",
        "",
        "after lunch",
    ],
)
def test_a_slot_the_portal_writes_another_way_is_schema_drift(entry: str) -> None:
    entries = ["15:30-16:00", entry]

    with pytest.raises(PortalError) as raised:
        parse_available_hours(entries, DAY, MADRID)

    assert raised.value.detail == drift_of("availability hours", entries)


async def days_of(harness: Harness, staff: StaffId, year: int, month: int) -> tuple[date, ...]:
    gateway, _ = harness.guardian_of("Mateo")
    return await gateway.call(lambda tx: read_available_days(tx, staff, year, month))


async def hours_of(harness: Harness, staff: StaffId, day: date) -> tuple[AvailableSlot, ...]:
    gateway, _ = harness.guardian_of("Mateo")
    return await gateway.call(lambda tx: read_available_hours(tx, staff, day))


async def test_reads_the_days_of_a_month_on_which_a_person_has_a_free_hour(
    harness: Harness,
) -> None:
    found = await days_of(harness, MUSIC, 2026, 1)

    assert found == tuple(date(2026, 1, day) for day in (6, 8, 13, 15, 20, 22, 27, 29))


async def test_each_person_offers_their_own_days(harness: Harness) -> None:
    mondays = await days_of(harness, TUTOR_B, 2026, 2)
    tuesdays_and_thursdays = await days_of(harness, MUSIC, 2026, 2)

    assert mondays == tuple(date(2026, 2, day) for day in (2, 9, 16, 23))
    assert tuesdays_and_thursdays == tuple(
        date(2026, 2, day) for day in (3, 5, 10, 12, 17, 19, 24, 26)
    )


async def test_today_and_the_past_are_not_offered(harness: Harness) -> None:
    january = await days_of(harness, MUSIC, 2026, 1)
    december = await days_of(harness, MUSIC, 2025, 12)

    assert date(2026, 1, 1) not in january
    assert december == ()


async def test_a_person_who_offers_nothing_has_no_free_days(harness: Harness) -> None:
    assert await days_of(harness, TUTOR_A, 2026, 1) == ()


async def test_the_portal_lists_a_text_for_each_free_hour_and_an_empty_object_for_none(
    harness: Harness,
) -> None:
    gateway, _ = harness.guardian_of("Mateo")

    async def ask(tx: Tx) -> tuple[wire.AvailableDaysReply, wire.AvailableDaysReply]:
        offering = wire.AvailableDaysParams(staff_id=MUSIC, month=1, year=2026)
        nothing = wire.AvailableDaysParams(staff_id=TUTOR_A, month=1, year=2026)
        return (
            await call_ws(tx, GET_AVAILABLE_DAYS, offering),
            await call_ws(tx, GET_AVAILABLE_DAYS, nothing),
        )

    offering, nothing = await gateway.call(ask)

    assert offering.entries is not None
    assert len(offering.entries) == 12
    assert offering.entries.count("2026,1,6") == 2
    assert offering.entries.count("2026,1,8") == 1
    assert nothing.entries is None


async def test_reads_the_free_hours_of_a_day(harness: Harness) -> None:
    assert await hours_of(harness, MUSIC, date(2026, 1, 6)) == (
        slot(6, (15, 30), (16, 0)),
        slot(6, (16, 0), (16, 30)),
    )
    assert await hours_of(harness, MUSIC, date(2026, 1, 8)) == (slot(8, (16, 30), (17, 0)),)


async def test_a_day_with_nothing_free_has_no_hours(harness: Harness) -> None:
    wednesday = await hours_of(harness, MUSIC, date(2026, 1, 7))
    nobody = await hours_of(harness, TUTOR_A, date(2026, 1, 6))

    assert (wednesday, nobody) == ((), ())


async def test_today_has_no_free_hours_even_on_a_day_the_person_usually_offers(
    harness: Harness,
) -> None:
    assert date(2026, 1, 1).isoweekday() == 4
    assert await hours_of(harness, MUSIC, date(2026, 1, 1)) == ()


async def test_hours_are_placed_in_the_zone_of_the_session(harness: Harness) -> None:
    gateway = harness.gateway(account="marta", credentials=harness.credentials(), zone=BOGOTA)

    found = await gateway.call(lambda tx: read_available_hours(tx, MUSIC, date(2026, 1, 8)))

    assert found == (slot(8, (16, 30), (17, 0), BOGOTA),)


async def test_a_person_that_no_child_of_the_family_can_meet_is_refused_and_not_read_as_empty(
    harness: Harness, failure: Failure
) -> None:
    gateway, _ = harness.guardian_of("Mateo")

    days = await failure(gateway.call(lambda tx: read_available_days(tx, STRANGER, 2026, 1)))
    hours = await failure(gateway.call(lambda tx: read_available_hours(tx, STRANGER, DAY)))

    assert days == WsRejected(call="WSReuniones.GetFechasDisponibles", status=500)
    assert hours == WsRejected(call="WSReuniones.GetHorasByFecha", status=500)


async def test_a_text_the_portal_writes_another_way_is_schema_drift(
    harness: Harness, failure: Failure
) -> None:
    harness.sim.options = SimOptions(availability_bad_entry=True)
    gateway, _ = harness.guardian_of("Mateo")

    days = await failure(gateway.call(lambda tx: read_available_days(tx, MUSIC, 2026, 1)))
    hours = await failure(gateway.call(lambda tx: read_available_hours(tx, MUSIC, DAY)))

    assert isinstance(days, SchemaDrift)
    assert days.where == "availability days"
    assert "tomorrow" in days.sample
    assert isinstance(hours, SchemaDrift)
    assert hours.where == "availability hours"
    assert "after lunch" in hours.sample
