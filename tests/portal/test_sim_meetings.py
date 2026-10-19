"""The simulator's meetings, its free hours, and the checks that make it as strict as the portal.

The readers of meetings and of free hours only mean something if the simulator refuses what the
portal refuses. These tests send each availability call wrong, one detail at a time, and they pin
down how the simulator lays out a meeting, which the agenda of the guardian shares.
"""

from datetime import date
from types import MappingProxyType
from typing import Any

import pytest
from pydantic import Field, TypeAdapter

from alexia_api.domain.errors import WsRejected
from alexia_api.domain.ids import parse_person_id
from alexia_api.domain.time import DateWindow
from alexia_api.portal import allowlist, wire
from alexia_api.portal.agenda import read_agenda
from alexia_api.portal.allowlist import WsCall
from alexia_api.portal.session import Tx
from alexia_api.portal.ws import call_ws
from alexia_api.sim.agenda import Term
from alexia_api.sim.meetings import (
    AGENDA_STATES,
    GRID,
    SimMeeting,
    SimOpening,
    cells_of,
    free_days,
    free_hours,
    interviews_of,
    rows_of,
)
from alexia_api.sim.world import DEMO_USER_A, default_world, synthetic_guid
from tests.harness import Failure, Harness

TERM = Term(2025)
TUESDAYS = SimOpening(2, ("15:30-16:00", "16:00-16:30"))
MUSIC = synthetic_guid(0x604)
TUTOR_B = synthetic_guid(0x603)


def meeting(
    number: int = 1, state: str = "Aceptada", held_on: tuple[int, int] = (10, 20), **fields: Any
) -> SimMeeting:
    return SimMeeting(
        id=synthetic_guid(0x7400 + number),
        state=state,
        held_on=held_on,
        staff="Ana Muestra Tutora",
        requester="Marta Ejemplo",
        **fields,
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("16:00", "16:30"),
        ("16:45", "17:15"),
        ("09:00", "09:30"),
        ("23:15", "23:45"),
        ("00:00", "00:30"),
    ],
)
def test_an_interview_of_the_agenda_lasts_half_an_hour(start: str, end: str) -> None:
    (occasion,) = interviews_of([meeting(start=start)])

    assert (occasion.starts, occasion.ends) == (start, end)


def test_an_interview_of_the_agenda_is_its_meeting() -> None:
    (occasion,) = interviews_of([meeting(7, "Pendiente", (11, 10), start="17:00")])

    assert occasion.id == synthetic_guid(0x7407)
    assert occasion.title == "Entrevista: Pendiente"
    assert (occasion.first, occasion.last) == ((11, 10), (11, 10))


@pytest.mark.parametrize("state", ["Cancelada", "Realizada", "Rechazada", "Solicitada", ""])
def test_a_meeting_in_another_state_is_not_in_the_agenda(state: str) -> None:
    assert interviews_of([meeting(state=state)]) == ()


@pytest.mark.parametrize("state", sorted(AGENDA_STATES))
def test_a_meeting_that_is_on_is_in_the_agenda(state: str) -> None:
    assert len(interviews_of([meeting(state=state)])) == 1


def test_a_row_has_twelve_cells_that_hold_what_the_page_shows() -> None:
    cells = cells_of(meeting(note="Traer <el> boletín", start="9:05"), "Lucía & Co", TERM)

    assert len(cells) == 12
    assert cells[0] == synthetic_guid(0x7401)
    assert 'title="Aceptada"' in cells[1]
    assert 'title="Participantes"' in cells[2]
    assert cells[4:10] == [
        "10",
        "20/10/2025",
        "9:05",
        "Marta Ejemplo",
        "Ana Muestra Tutora",
        "Lucía &amp; Co",
    ]
    assert cells[10] == "Traer &lt;el&gt; boletín"
    assert cells[3] == cells[11] == "&nbsp;"


def test_a_meeting_without_a_note_has_a_blank_note_cell() -> None:
    assert cells_of(meeting(), "Lucía", TERM)[10] == "&nbsp;"


def test_a_meeting_takes_the_year_of_the_school_year_it_is_laid_out_for() -> None:
    september = cells_of(meeting(held_on=(9, 25)), "Lucía", TERM)[5]
    january = cells_of(meeting(held_on=(1, 15)), "Lucía", TERM)[5]
    next_term = cells_of(meeting(held_on=(9, 25)), "Lucía", Term(2026))[5]

    assert (september, january, next_term) == ("25/09/2025", "15/01/2026", "25/09/2026")


def test_the_date_can_be_written_the_wrong_way_on_purpose() -> None:
    assert cells_of(meeting(), "Lucía", TERM, date_as_iso=True)[5] == "2025-10-20"


def test_a_state_with_markup_characters_stays_inside_its_attribute() -> None:
    cells = cells_of(meeting(state='A"B'), "Lucía", TERM)

    assert 'title="A&quot;B"' in cells[1]


def test_rows_follow_the_page_sort_which_puts_the_month_before_the_year() -> None:
    held = [
        meeting(1, held_on=(10, 20)),
        meeting(2, held_on=(1, 15)),
        meeting(3, held_on=(9, 25)),
        meeting(4, held_on=(10, 2)),
    ]

    rows = rows_of(held, "Lucía", TERM)

    assert [row["id"] for row in rows] == [
        synthetic_guid(0x7400 + number) for number in (2, 3, 4, 1)
    ]


def test_a_row_is_the_id_and_its_cells() -> None:
    (row,) = rows_of([meeting()], "Lucía", TERM)

    assert row == {"id": synthetic_guid(0x7401), "cell": cells_of(meeting(), "Lucía", TERM)}


@pytest.mark.parametrize("count", [0, 5, 11, 13])
def test_the_rows_can_be_cut_or_padded_on_purpose(count: int) -> None:
    (row,) = rows_of([meeting()], "Lucía", TERM, cell_count=count)

    assert len(row["cell"]) == count  # type: ignore[arg-type]


def test_the_grid_is_the_portals_meetings_page() -> None:
    assert GRID.path == "/ACWeb/paginas/Grids/Entrevistas.aspx"
    assert GRID.grid_id.endswith("CmptEntrevistas_gridReuniones1")
    assert (GRID.sort, GRID.order) == ("Unbound_Mes asc, Fecha", "asc")


def test_a_person_offers_the_hours_of_a_weekday_on_every_such_day_after_today() -> None:
    today = date(2026, 1, 1)

    assert free_hours([TUESDAYS], date(2026, 1, 6), today) == ["15:30-16:00", "16:00-16:30"]
    assert free_hours([TUESDAYS], date(2026, 1, 7), today) == []


def test_today_and_the_past_have_no_free_hours() -> None:
    tuesday = date(2026, 1, 6)

    assert free_hours([TUESDAYS], tuesday, today=tuesday) == []
    assert free_hours([TUESDAYS], tuesday, today=date(2026, 1, 7)) == []
    assert free_hours([TUESDAYS], tuesday, today=date(2026, 1, 5)) != []


def test_several_openings_on_one_weekday_add_up() -> None:
    other = SimOpening(2, ("17:00-17:30",))

    assert free_hours([TUESDAYS, other], date(2026, 1, 6), date(2026, 1, 1)) == [
        "15:30-16:00",
        "16:00-16:30",
        "17:00-17:30",
    ]


def test_a_month_has_one_text_for_each_free_hour_of_each_day() -> None:
    entries = free_days([TUESDAYS], 2026, 1, today=date(2026, 1, 1))

    assert entries == [
        text for day in (6, 13, 20, 27) for text in (f"2026,1,{day}", f"2026,1,{day}")
    ]


@pytest.mark.parametrize(
    ("year", "weekday", "last"),
    [(2028, 2, "2028,2,29"), (2027, 3, "2027,2,24"), (2028, 5, "2028,2,25")],
)
def test_the_days_of_a_month_run_to_its_last_day(year: int, weekday: int, last: str) -> None:
    opening = SimOpening(weekday, ("10:00-10:30",))

    assert free_days([opening], year, 2, today=date(year, 1, 1))[-1] == last


def test_nothing_offered_is_no_text() -> None:
    assert free_days([], 2026, 1, today=date(2026, 1, 1)) == []


def test_the_staff_that_offer_hours_are_the_music_teacher_and_one_tutor() -> None:
    offering = {
        member.id
        for family in default_world().families
        for child in family.children
        for member in child.staff
        if member.openings
    }

    assert offering == {MUSIC, TUTOR_B}


async def guardian_interviews(harness: Harness, first_name: str, guardian: int) -> list[str]:
    gateway, _ = harness.guardian_of(first_name)
    window = DateWindow(date(2025, 9, 1), date(2026, 7, 31))
    person = parse_person_id(synthetic_guid(guardian))

    events = await gateway.call(lambda tx: read_agenda(tx, "guardian", person, window))

    return [event.id for event in events if event.kind == "interview"]


async def test_the_agenda_of_a_guardian_holds_the_meetings_that_are_on(harness: Harness) -> None:
    marta = await guardian_interviews(harness, "Lucía", 0x301)
    pablo = await guardian_interviews(harness, "Hugo", 0x311)

    assert marta == [f"{synthetic_guid(0x7301)}|2025-10-20"]
    assert pablo == [f"{synthetic_guid(0x7311)}|2025-11-10"]


async def test_a_meeting_of_any_child_of_the_family_is_in_the_agenda_of_the_guardian(
    harness: Harness,
) -> None:
    _, mateo = harness.guardian_of("Mateo")
    harness.revise_child(
        DEMO_USER_A, mateo, meetings=(meeting(5, "Pendiente", (11, 12), start="15:30"),)
    )

    found = await guardian_interviews(harness, "Lucía", 0x301)

    assert found == [
        f"{synthetic_guid(0x7301)}|2025-10-20",
        f"{synthetic_guid(0x7405)}|2025-11-12",
    ]


async def test_a_meeting_that_is_cancelled_leaves_the_agenda_of_the_guardian(
    harness: Harness,
) -> None:
    _, lucia = harness.guardian_of("Lucía")
    harness.revise_child(DEMO_USER_A, lucia, meetings=(meeting(state="Cancelada"),))

    assert await guardian_interviews(harness, "Lucía", 0x301) == []


class LooseDays(wire.RequestModel):
    """The month call's parameters with the types left open, so a test can get them wrong."""

    staff_id: str = Field(alias="guidEmpleado")
    month: object = Field(alias="mes")
    year: object = Field(alias="anyo")


class LooseHours(wire.RequestModel):
    staff_id: str = Field(alias="guidEmpleado")
    day: object = Field(alias="fecha")


class ExtraDays(LooseDays):
    surprise: str = Field(alias="otro")


class ExtraHours(LooseHours):
    surprise: str = Field(alias="otro")


def loose[P: wire.RequestModel](
    monkeypatch: pytest.MonkeyPatch, method: str, params: type[P], reply: type[Any]
) -> WsCall[P, Any]:
    """A lookalike of a call that sends whatever the test wants, which the allowlist accepts."""
    call = WsCall("WSReuniones", method, "read", params, TypeAdapter(reply))
    table = MappingProxyType({**allowlist.ALLOWLIST, call.name: call})
    monkeypatch.setattr(allowlist, "ALLOWLIST", table)
    return call


async def send[P: wire.RequestModel, R](harness: Harness, call: WsCall[P, R], params: P) -> R:
    gateway, _ = harness.guardian_of("Mateo")

    async def ask(tx: Tx) -> R:
        return await call_ws(tx, call, params)

    return await gateway.call(ask)


@pytest.mark.parametrize(
    ("month", "year"),
    [
        ("1", 2026),
        (1, "2026"),
        (0, 2026),
        (13, 2026),
        (1, 0),
        (1, 10_000),
        (True, 2026),
        (1, True),
        (1.5, 2026),
        (None, 2026),
    ],
)
async def test_a_month_call_with_a_bad_month_or_year_is_refused(
    harness: Harness,
    failure: Failure,
    monkeypatch: pytest.MonkeyPatch,
    month: object,
    year: object,
) -> None:
    call = loose(monkeypatch, "GetFechasDisponibles", LooseDays, dict[str, object])

    detail = await failure(send(harness, call, LooseDays(staff_id=MUSIC, month=month, year=year)))

    assert detail == WsRejected(call="WSReuniones.GetFechasDisponibles", status=500)


async def test_a_month_call_with_a_field_too_many_is_refused(
    harness: Harness, failure: Failure, monkeypatch: pytest.MonkeyPatch
) -> None:
    call = loose(monkeypatch, "GetFechasDisponibles", ExtraDays, dict[str, object])
    params = ExtraDays(staff_id=MUSIC, month=1, year=2026, surprise="x")

    detail = await failure(send(harness, call, params))

    assert detail == WsRejected(call="WSReuniones.GetFechasDisponibles", status=500)


@pytest.mark.parametrize("staff", [synthetic_guid(0x999), "not-a-guid", ""])
async def test_a_month_call_for_a_person_nobody_in_the_family_can_meet_is_refused(
    harness: Harness, failure: Failure, monkeypatch: pytest.MonkeyPatch, staff: str
) -> None:
    call = loose(monkeypatch, "GetFechasDisponibles", LooseDays, dict[str, object])

    detail = await failure(send(harness, call, LooseDays(staff_id=staff, month=1, year=2026)))

    assert detail == WsRejected(call="WSReuniones.GetFechasDisponibles", status=500)


@pytest.mark.parametrize("day", [20260106, None, True, ["2026-01-06"]])
async def test_an_hours_call_with_a_day_that_is_not_text_is_refused(
    harness: Harness, failure: Failure, monkeypatch: pytest.MonkeyPatch, day: object
) -> None:
    call = loose(monkeypatch, "GetHorasByFecha", LooseHours, dict[str, object])

    detail = await failure(send(harness, call, LooseHours(staff_id=MUSIC, day=day)))

    assert detail == WsRejected(call="WSReuniones.GetHorasByFecha", status=500)


async def test_an_hours_call_with_a_field_too_many_is_refused(
    harness: Harness, failure: Failure, monkeypatch: pytest.MonkeyPatch
) -> None:
    call = loose(monkeypatch, "GetHorasByFecha", ExtraHours, dict[str, object])
    params = ExtraHours(staff_id=MUSIC, day="2026-01-06", surprise="x")

    detail = await failure(send(harness, call, params))

    assert detail == WsRejected(call="WSReuniones.GetHorasByFecha", status=500)


@pytest.mark.parametrize("staff", [synthetic_guid(0x999), "not-a-guid", ""])
async def test_an_hours_call_for_a_person_nobody_in_the_family_can_meet_is_refused(
    harness: Harness, failure: Failure, monkeypatch: pytest.MonkeyPatch, staff: str
) -> None:
    call = loose(monkeypatch, "GetHorasByFecha", LooseHours, dict[str, object])

    detail = await failure(send(harness, call, LooseHours(staff_id=staff, day="2026-01-06")))

    assert detail == WsRejected(call="WSReuniones.GetHorasByFecha", status=500)


@pytest.mark.parametrize(
    "day",
    [
        "/Date(1767657600000)/",
        "2026-02-30",
        "2026-13-01",
        "20260106",
        "2026-1-6",
        "06/01/2026",
        "2026-01-06T00:00:00",
        "2026-W02-2",
        "",
        "tomorrow",
    ],
)
async def test_an_hours_call_with_a_day_that_is_not_written_as_iso_text_finds_nothing(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, day: str
) -> None:
    call = loose(monkeypatch, "GetHorasByFecha", LooseHours, wire.AvailableHoursReply)

    reply = await send(harness, call, LooseHours(staff_id=MUSIC, day=day))

    assert reply.hours is None


async def test_the_same_call_with_an_iso_day_finds_the_hours(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    call = loose(monkeypatch, "GetHorasByFecha", LooseHours, wire.AvailableHoursReply)

    reply = await send(harness, call, LooseHours(staff_id=MUSIC, day="2026-01-06"))

    assert reply.hours == ["15:30-16:00", "16:00-16:30"]


async def test_the_switch_for_a_bad_text_leaves_an_empty_answer_empty(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.sim.options.availability_bad_entry = True
    call = loose(monkeypatch, "GetHorasByFecha", LooseHours, wire.AvailableHoursReply)

    reply = await send(harness, call, LooseHours(staff_id=MUSIC, day="2026-01-07"))

    assert reply.hours is None
