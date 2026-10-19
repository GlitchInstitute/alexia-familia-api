"""The registry gives each account its own gateway and cache, and finds children through them."""

import asyncio
from datetime import date, timedelta

import pytest

from alexia_api.clock import ManualClock
from alexia_api.config import CacheTtls, ConfigError
from alexia_api.domain.accounts import Blocked, Capabilities, LoggedIn, LoggedOut
from alexia_api.domain.children import TrackingCounters
from alexia_api.domain.errors import BreakerOpen, InvalidCredentials
from alexia_api.domain.ids import parse_account_id
from alexia_api.domain.messages import FolderName, Message, MessageSummary
from alexia_api.domain.security import Principal
from alexia_api.domain.time import DateWindow
from alexia_api.portal.breaker import BreakerStore
from alexia_api.portal.inbox import Feed
from alexia_api.services.errors import NotFoundError
from alexia_api.services.registry import Directory, Registry
from alexia_api.sim.world import DEMO_PASSWORD_B, DEMO_USER_A, DEMO_USER_B, synthetic_guid
from tests.harness import A_NEW_MESSAGE, Failure, Harness, teacher

LUCIA = synthetic_guid(0x101)
MATEO = synthetic_guid(0x102)
HUGO = synthetic_guid(0x111)
TUTOR_B = synthetic_guid(0x603)
MUSIC = synthetic_guid(0x604)
UNREAD = synthetic_guid(0x1001)
WITH_FILE = synthetic_guid(0x1002)
MESSAGE_DATA = "GetDatosPaginaComunicado"
AGENDA_FEED = "ControladorAgenda.ashx"
HOME = "HomeMetro.aspx"
WEEK = DateWindow(first=date(2025, 10, 13), last=date(2025, 10, 19))
NEXT_WEEK = DateWindow(first=date(2025, 10, 20), last=date(2025, 10, 26))


async def test_accounts_are_kept_in_the_order_they_were_configured(harness: Harness) -> None:
    registry = harness.registry()

    assert [runtime.account for runtime in registry.accounts] == ["marta", "pablo"]


@pytest.mark.parametrize("name", ["nobody", "Marta Family", "../etc", ""])
async def test_an_account_that_is_not_held_is_not_found(harness: Harness, name: str) -> None:
    registry = harness.registry()

    with pytest.raises(NotFoundError) as raised:
        registry.get(name)

    assert (raised.value.kind, raised.value.reference) == ("account", name)


async def test_the_directory_names_the_guardian_and_gives_each_child_a_slug(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")

    directory = (await runtime.directory()).value

    assert directory.guardian is not None
    assert directory.guardian.first_name == "Marta"
    assert [(child.id, child.slug) for child in directory.children] == [
        (LUCIA, "lucia"),
        (MATEO, "mateo"),
    ]


async def test_each_account_sees_only_the_children_the_portal_lists_for_it(
    harness: Harness,
) -> None:
    registry = harness.registry()

    marta = (await registry.get("marta").directory()).value
    pablo = (await registry.get("pablo").directory()).value

    assert [child.slug for child in marta.children] == ["lucia", "mateo"]
    assert [child.slug for child in pablo.children] == ["hugo", "alba"]


async def test_a_second_look_at_the_directory_does_not_call_the_portal(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    first = await runtime.directory()
    calls = len(harness.sim.requests)

    second = await runtime.directory()

    assert (first.status, second.status) == ("miss", "hit")
    assert len(harness.sim.requests) == calls


async def test_a_fresh_look_reads_the_portal_again_but_keeps_the_session(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    await runtime.directory()
    calls = len(harness.sim.requests)

    again = await runtime.directory(fresh=True)

    assert again.status == "bypass"
    assert len(harness.sim.requests) > calls
    assert harness.requests_to("/Validar") == 1


async def test_the_directory_is_read_again_once_its_time_to_live_is_up(
    harness: Harness, clock: ManualClock
) -> None:
    runtime = harness.registry().get("marta")
    await runtime.directory()

    clock.advance(899)
    assert (await runtime.directory()).status == "hit"
    clock.advance(2)

    assert (await runtime.directory()).status == "miss"
    assert harness.requests_to("/Validar") == 1


async def test_a_child_is_found_by_slug_or_by_student_id_in_any_case(harness: Harness) -> None:
    runtime = harness.registry().get("marta")

    by_slug = (await runtime.child("lucia")).value
    by_id = (await runtime.child(LUCIA.upper())).value

    assert by_slug == by_id
    assert by_slug.first_name == "Lucía"


@pytest.mark.parametrize("reference", ["hugo", HUGO, "nobody", ""])
async def test_a_child_the_account_does_not_list_is_not_found(
    harness: Harness, reference: str
) -> None:
    runtime = harness.registry().get("marta")

    with pytest.raises(NotFoundError) as raised:
        await runtime.child(reference)

    assert (raised.value.kind, raised.value.reference) == ("child", reference)


async def test_a_missing_child_is_decided_from_the_cache_without_calling_the_portal(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    await runtime.directory()
    calls = len(harness.sim.requests)

    with pytest.raises(NotFoundError):
        await runtime.child("nobody")

    assert len(harness.sim.requests) == calls


async def test_a_child_lookup_reports_how_its_directory_was_found(harness: Harness) -> None:
    runtime = harness.registry().get("marta")

    first = await runtime.child("lucia")
    second = await runtime.child("mateo")
    third = await runtime.child("mateo", fresh=True)

    assert (first.status, second.status, third.status) == ("miss", "hit", "bypass")


async def test_pinned_slugs_win_over_the_ones_derived_from_names(harness: Harness) -> None:
    settings = harness.settings(
        accounts={"marta": harness.account_settings(slugs={"first-born": LUCIA})}
    )
    runtime = harness.registry(settings).get("marta")

    directory = (await runtime.directory()).value

    assert [child.slug for child in directory.children] == ["first-born", "mateo"]
    assert (await runtime.child("first-born")).value.id == LUCIA
    with pytest.raises(NotFoundError):
        await runtime.child("lucia")


async def test_tracking_is_read_for_the_child_asked_about(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    mateo = (await runtime.child("mateo")).value

    assert (await runtime.tracking(lucia)).value == TrackingCounters(
        tasks=3, activities=1, notes=0, tests=2, incidents=0
    )
    assert (await runtime.tracking(mateo)).value == TrackingCounters(
        tasks=1, activities=0, notes=2, tests=0, incidents=1
    )


async def test_tracking_is_cached_for_each_child_on_its_own(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    mateo = (await runtime.child("mateo")).value
    await runtime.tracking(lucia)
    calls = len(harness.sim.requests)

    again = await runtime.tracking(lucia)
    other = await runtime.tracking(mateo)

    assert (again.status, other.status) == ("hit", "miss")
    assert len(harness.sim.requests) == calls + 1


async def test_a_time_to_live_of_zero_turns_the_cache_off(harness: Harness) -> None:
    settings = harness.settings(cache=CacheTtls(tracking=0))
    runtime = harness.registry(settings).get("marta")
    lucia = (await runtime.child("lucia")).value

    first = await runtime.tracking(lucia)
    second = await runtime.tracking(lucia)

    assert (first.status, second.status) == ("miss", "miss")


async def test_staff_comes_from_the_roster_of_that_child(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    mateo = (await runtime.child("mateo")).value

    lucia_staff = (await runtime.staff(lucia)).value
    mateo_staff = (await runtime.staff(mateo)).value

    assert [(member.id, member.role) for member in lucia_staff] == [
        (synthetic_guid(0x601), "Tutora"),
        (synthetic_guid(0x602), "Matemáticas"),
    ]
    assert [(member.id, member.role) for member in mateo_staff] == [
        (synthetic_guid(0x603), "Tutora"),
        (synthetic_guid(0x604), "Música"),
    ]


async def test_staff_is_cached_for_longer_than_tracking(
    harness: Harness, clock: ManualClock
) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    await runtime.tracking(lucia)
    await runtime.staff(lucia)

    clock.advance(300)

    assert (await runtime.tracking(lucia)).status == "miss"
    assert (await runtime.staff(lucia)).status == "hit"


async def test_absences_are_read_for_the_child_asked_about(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    mateo = (await runtime.child("mateo")).value

    assert (await runtime.absences(lucia)).value == ()
    assert [absence.id for absence in (await runtime.absences(mateo)).value] == [
        synthetic_guid(0x7501 + index) for index in range(4)
    ]


async def test_absences_are_cached_for_each_child_on_their_own(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    mateo = (await runtime.child("mateo")).value
    await runtime.absences(lucia)
    calls = len(harness.sim.requests)

    again = await runtime.absences(lucia)
    other = await runtime.absences(mateo)

    assert (again.status, other.status) == ("hit", "miss")
    assert len(harness.sim.requests) == calls + 2


async def test_absences_and_tracking_of_a_child_are_kept_apart(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    mateo = (await runtime.child("mateo")).value
    await runtime.tracking(mateo)

    assert (await runtime.absences(mateo)).status == "miss"
    assert (await runtime.tracking(mateo)).status == "hit"


async def test_a_fresh_look_at_absences_reads_the_portal_again(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    mateo = (await runtime.child("mateo")).value
    await runtime.absences(mateo)
    calls = len(harness.sim.requests)

    again = await runtime.absences(mateo, fresh=True)

    assert again.status == "bypass"
    assert len(harness.sim.requests) == calls + 2


async def test_meetings_are_read_for_the_child_asked_about(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    mateo = (await runtime.child("mateo")).value

    assert [meeting.id for meeting in (await runtime.meetings(lucia)).value] == [
        synthetic_guid(number) for number in (0x7302, 0x7301, 0x7303)
    ]
    assert (await runtime.meetings(mateo)).value == ()


async def test_meetings_are_cached_for_each_child_on_their_own(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    mateo = (await runtime.child("mateo")).value
    await runtime.meetings(lucia)
    calls = len(harness.sim.requests)

    again = await runtime.meetings(lucia)
    other = await runtime.meetings(mateo)

    assert (again.status, other.status) == ("hit", "miss")
    assert len(harness.sim.requests) == calls + 2


async def test_meetings_and_absences_of_a_child_are_kept_apart(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    mateo = (await runtime.child("mateo")).value
    await runtime.absences(mateo)

    assert (await runtime.meetings(mateo)).status == "miss"
    assert (await runtime.absences(mateo)).status == "hit"


async def test_a_fresh_look_at_meetings_reads_the_portal_again(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    await runtime.meetings(lucia)
    calls = len(harness.sim.requests)

    again = await runtime.meetings(lucia, fresh=True)

    assert again.status == "bypass"
    assert len(harness.sim.requests) == calls + 2


async def test_the_free_days_and_hours_are_read_for_a_person_on_the_staff_of_the_child(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    mateo = (await runtime.child("mateo")).value

    days = (await runtime.available_days(mateo, MUSIC, 2026, 1)).value
    slots = (await runtime.available_hours(mateo, MUSIC, date(2026, 1, 6))).value

    assert (days[0], days[-1], len(days)) == (date(2026, 1, 6), date(2026, 1, 29), 8)
    assert [(slot.starts_at.hour, slot.starts_at.minute) for slot in slots] == [(15, 30), (16, 0)]


@pytest.mark.parametrize("reference", [synthetic_guid(0x999), "not-a-guid", "", "x" * 300])
async def test_a_person_who_is_not_on_the_staff_of_the_child_is_not_found(
    harness: Harness, reference: str
) -> None:
    runtime = harness.registry().get("marta")
    mateo = (await runtime.child("mateo")).value

    with pytest.raises(NotFoundError) as raised:
        await runtime.available_days(mateo, reference, 2026, 1)
    with pytest.raises(NotFoundError):
        await runtime.available_hours(mateo, reference, date(2026, 1, 6))

    assert (raised.value.kind, raised.value.reference) == ("staff", reference)


async def test_a_teacher_of_a_sibling_is_not_found_for_this_child(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value

    with pytest.raises(NotFoundError) as raised:
        await runtime.available_days(lucia, MUSIC, 2026, 1)

    assert raised.value.kind == "staff"


async def test_an_unknown_person_costs_no_portal_call_once_the_staff_list_is_stored(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    mateo = (await runtime.child("mateo")).value
    await runtime.staff(mateo)
    calls = len(harness.sim.requests)

    with pytest.raises(NotFoundError):
        await runtime.available_days(mateo, synthetic_guid(0x999), 2026, 1)

    assert len(harness.sim.requests) == calls


async def test_the_id_of_a_person_may_be_written_in_capital_letters(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    mateo = (await runtime.child("mateo")).value

    days = await runtime.available_days(mateo, MUSIC.upper(), 2026, 1)

    assert len(days.value) == 8


async def test_free_hours_are_stored_for_each_person_month_and_day_on_their_own(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    mateo = (await runtime.child("mateo")).value
    await runtime.available_days(mateo, MUSIC, 2026, 1)
    await runtime.available_hours(mateo, MUSIC, date(2026, 1, 6))

    statuses = [
        (await runtime.available_days(mateo, MUSIC, 2026, 1)).status,
        (await runtime.available_hours(mateo, MUSIC, date(2026, 1, 6))).status,
        (await runtime.available_days(mateo, MUSIC, 2026, 2)).status,
        (await runtime.available_hours(mateo, MUSIC, date(2026, 1, 8))).status,
        (await runtime.available_days(mateo, TUTOR_B, 2026, 1)).status,
    ]

    assert statuses == ["hit", "hit", "miss", "miss", "miss"]


async def test_the_free_hours_of_one_person_are_shared_by_the_children_who_have_them(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    mateo = (await runtime.child("mateo")).value
    lucia = (await runtime.child("lucia")).value
    harness.revise_child(DEMO_USER_A, LUCIA, staff=(teacher(0x604),))
    await runtime.available_days(mateo, MUSIC, 2026, 1)

    shared = await runtime.available_days(lucia, MUSIC, 2026, 1)

    assert shared.status == "hit"
    assert harness.requests_to("GetFechasDisponibles") == 1


async def test_a_fresh_look_at_free_hours_reads_them_again_and_not_the_staff_list(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    mateo = (await runtime.child("mateo")).value
    await runtime.available_days(mateo, MUSIC, 2026, 1)

    again = await runtime.available_days(mateo, MUSIC, 2026, 1, fresh=True)

    assert again.status == "bypass"
    assert harness.requests_to("GetFechasDisponibles") == 2
    assert harness.requests_to("GetEmpleadosByHijo") == 1


async def test_an_account_keeps_only_the_latest_answers_about_free_hours(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alexia_api.services.registry.MAX_CACHED_AVAILABILITY", 2)
    runtime = harness.registry().get("marta")
    mateo = (await runtime.child("mateo")).value
    months = [(2026, 1), (2026, 2), (2026, 3)]
    for year, month in months:
        await runtime.available_days(mateo, MUSIC, year, month)

    statuses = [
        (await runtime.available_days(mateo, MUSIC, year, month)).status
        for year, month in reversed(months)
    ]

    assert statuses == ["hit", "hit", "miss"]


async def test_a_run_of_odd_months_does_not_push_out_the_lists_of_the_account(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alexia_api.services.registry.MAX_CACHED_AVAILABILITY", 1)
    runtime = harness.registry().get("marta")
    mateo = (await runtime.child("mateo")).value
    for month in (1, 2, 3):
        await runtime.available_days(mateo, MUSIC, 2026, month)

    assert (await runtime.directory()).status == "hit"
    assert (await runtime.staff(mateo)).status == "hit"


async def test_the_agenda_of_a_child_holds_only_the_days_asked_for(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value

    week = (await runtime.agenda(lucia, WEEK)).value

    assert [event.kind for event in week].count("lesson") == 30
    assert {event.starts_at.date() for event in week} <= set(WEEK.days())


async def test_each_child_has_an_agenda_of_its_own(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    mateo = (await runtime.child("mateo")).value

    lucias = (await runtime.agenda(lucia, WEEK)).value
    mateos = (await runtime.agenda(mateo, WEEK)).value

    assert {event.id for event in lucias}.isdisjoint({event.id for event in mateos})


async def test_a_range_is_read_once_and_kept_for_ten_minutes(
    harness: Harness, clock: ManualClock
) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    first = await runtime.agenda(lucia, WEEK)
    reads = harness.requests_to(AGENDA_FEED)

    clock.advance(599)
    second = await runtime.agenda(lucia, WEEK)
    clock.advance(2)
    third = await runtime.agenda(lucia, WEEK)

    assert [answer.status for answer in (first, second, third)] == ["miss", "hit", "miss"]
    assert second.value == first.value
    assert harness.requests_to(AGENDA_FEED) == reads + 1


async def test_every_range_and_every_person_is_kept_under_a_key_of_its_own(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    mateo = (await runtime.child("mateo")).value

    async def everything() -> list[tuple[str, tuple[object, ...]]]:
        answers = [
            await runtime.agenda(lucia, WEEK),
            await runtime.agenda(lucia, NEXT_WEEK),
            await runtime.agenda(mateo, WEEK),
            await runtime.guardian_agenda(NEXT_WEEK),
        ]
        return [(answer.status, answer.value) for answer in answers]

    first = await everything()
    again = await everything()

    assert [status for status, _ in first] == ["miss"] * 4
    assert [status for status, _ in again] == ["hit"] * 4
    assert [value for _, value in again] == [value for _, value in first]
    assert len({value for _, value in first}) == 4


async def test_two_ranges_that_start_on_the_same_day_are_kept_apart(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    one_day = DateWindow(first=WEEK.first, last=WEEK.first)

    week = await runtime.agenda(lucia, WEEK)
    day = await runtime.agenda(lucia, one_day)

    assert (week.status, day.status) == ("miss", "miss")
    assert {event.starts_at.date() for event in day.value} == {WEEK.first}
    assert len(week.value) > len(day.value)


async def test_a_fresh_look_at_an_agenda_reads_the_portal_again(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    await runtime.agenda(lucia, WEEK)
    reads = harness.requests_to(AGENDA_FEED)

    again = await runtime.agenda(lucia, WEEK, fresh=True)

    assert again.status == "bypass"
    assert harness.requests_to(AGENDA_FEED) == reads + 1


async def test_a_time_to_live_of_zero_turns_the_store_of_agendas_off(harness: Harness) -> None:
    runtime = harness.registry(harness.settings(cache=CacheTtls(agenda=0))).get("marta")
    lucia = (await runtime.child("lucia")).value

    first = await runtime.agenda(lucia, WEEK)
    second = await runtime.agenda(lucia, WEEK)

    assert (first.status, second.status) == ("miss", "miss")


async def test_an_account_keeps_only_the_latest_ranges_of_its_agendas(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alexia_api.services.registry.MAX_CACHED_AGENDAS", 2)
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    days = [DateWindow(first=date(2025, 10, day), last=date(2025, 10, day)) for day in (13, 14, 15)]
    for window in days:
        await runtime.agenda(lucia, window)

    statuses = [(await runtime.agenda(lucia, window)).status for window in reversed(days)]

    assert statuses == ["hit", "hit", "miss"]


async def test_a_run_of_odd_ranges_does_not_push_out_the_list_of_children(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alexia_api.services.registry.MAX_CACHED_AGENDAS", 1)
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value
    for day in (13, 14, 15):
        await runtime.agenda(lucia, DateWindow(first=date(2025, 10, day), last=date(2025, 10, day)))

    assert (await runtime.directory()).status == "hit"


async def test_the_agenda_of_the_guardian_holds_interviews_and_no_lessons(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")

    events = (await runtime.guardian_agenda(NEXT_WEEK)).value

    assert [event.title for event in events if event.kind == "interview"] == [
        "Entrevista: Aceptada"
    ]
    assert "lesson" not in {event.kind for event in events}


async def test_the_guardian_is_looked_up_only_when_the_portal_has_to_be_asked(
    harness: Harness, clock: ManualClock
) -> None:
    runtime = harness.registry(harness.settings(cache=CacheTtls(agenda=100_000))).get("marta")
    first = await runtime.guardian_agenda(WEEK)
    homes = harness.requests_to(HOME)

    clock.advance(1000)
    second = await runtime.guardian_agenda(WEEK)

    assert (first.status, second.status) == ("miss", "hit")
    assert harness.requests_to(HOME) == homes


async def test_a_login_that_lists_no_guardian_has_no_guardian_agenda(harness: Harness) -> None:
    harness.sim.options.home_without_guardian = True
    runtime = harness.registry().get("marta")

    with pytest.raises(NotFoundError) as raised:
        await runtime.guardian_agenda(WEEK)

    assert (raised.value.kind, raised.value.reference) == ("guardian", "marta")
    assert harness.requests_to(AGENDA_FEED) == 0
    lucia = (await runtime.child("lucia")).value
    assert (await runtime.agenda(lucia, WEEK)).value


async def test_a_fresh_look_finds_a_guardian_that_the_portal_began_to_list(
    harness: Harness,
) -> None:
    harness.sim.options.home_without_guardian = True
    runtime = harness.registry().get("marta")
    with pytest.raises(NotFoundError):
        await runtime.guardian_agenda(NEXT_WEEK)
    harness.sim.options.home_without_guardian = False

    with pytest.raises(NotFoundError):
        await runtime.guardian_agenda(NEXT_WEEK)
    found = await runtime.guardian_agenda(NEXT_WEEK, fresh=True)

    assert found.status == "bypass"
    assert [event.kind for event in found.value if event.kind == "interview"] == ["interview"]


@pytest.mark.parametrize(("name", "received", "sent"), [("marta", 8, 2), ("pablo", 3, 1)])
async def test_each_account_lists_the_folders_of_its_own_mailbox(
    harness: Harness, name: str, received: int, sent: int
) -> None:
    folders = (await harness.registry().get(name).folders()).value

    assert [(folder.name, folder.count) for folder in folders] == [
        ("received", received),
        ("sent", sent),
    ]


async def test_the_folders_are_kept_for_five_minutes(harness: Harness, clock: ManualClock) -> None:
    runtime = harness.registry().get("marta")
    first = await runtime.folders()
    calls = len(harness.sim.requests)

    clock.advance(299)
    second = await runtime.folders()
    assert len(harness.sim.requests) == calls
    clock.advance(2)
    third = await runtime.folders()

    assert (first.status, second.status, third.status) == ("miss", "hit", "miss")


async def test_a_fresh_look_at_the_folders_reads_the_portal_again(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    await runtime.folders()
    calls = len(harness.sim.requests)

    again = await runtime.folders(fresh=True)

    assert again.status == "bypass"
    assert len(harness.sim.requests) > calls


async def test_the_messages_of_each_folder_and_each_account_are_kept_apart(
    harness: Harness,
) -> None:
    registry = harness.registry()
    marta = registry.get("marta")

    received = await marta.messages("received")
    sent = await marta.messages("sent")
    pablo = await registry.get("pablo").messages("received")

    received_ids, sent_ids, pablo_ids = (
        {message.id for message in listing.value.messages} for listing in (received, sent, pablo)
    )
    assert (len(received_ids), len(sent_ids), len(pablo_ids)) == (8, 2, 3)
    assert received_ids.isdisjoint(sent_ids)
    assert received_ids.isdisjoint(pablo_ids)
    assert [listing.status for listing in (received, sent, pablo)] == ["miss", "miss", "miss"]


async def test_every_kind_of_answer_is_kept_under_a_key_of_its_own(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    lucia = (await runtime.child("lucia")).value

    async def everything() -> list[object]:
        return [
            (await runtime.directory()).value,
            (await runtime.folders()).value,
            (await runtime.messages("received")).value,
            (await runtime.messages("sent")).value,
            (await runtime.message("received", WITH_FILE)).value,
            (await runtime.tracking(lucia)).value,
            (await runtime.staff(lucia)).value,
        ]

    first = await everything()
    again = await everything()

    assert [type(answer) for answer in first] == [
        Directory,
        tuple,
        Feed,
        Feed,
        Message,
        TrackingCounters,
        tuple,
    ]
    assert again == first


async def test_a_message_list_is_read_once_however_often_it_is_asked_for(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    first = await runtime.messages("received")
    calls = len(harness.sim.requests)

    second = await runtime.messages("received")

    assert (first.status, second.status) == ("miss", "hit")
    assert second.value == first.value
    assert len(harness.sim.requests) == calls


async def test_a_message_list_is_read_again_after_two_minutes(
    harness: Harness, clock: ManualClock
) -> None:
    runtime = harness.registry().get("marta")
    await runtime.messages("received")

    clock.advance(119)
    assert (await runtime.messages("received")).status == "hit"
    clock.advance(2)

    assert (await runtime.messages("received")).status == "miss"


async def test_a_fresh_look_sees_a_message_that_arrived_since(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    before = await runtime.messages("received")
    harness.deliver("marta.ejemplo", A_NEW_MESSAGE)

    stale = await runtime.messages("received")
    fresh = await runtime.messages("received", fresh=True)

    assert stale.value == before.value
    assert fresh.status == "bypass"
    assert len(fresh.value.messages) == len(before.value.messages) + 1
    assert fresh.value.messages[0].subject == "Nuevo aviso"


async def test_a_message_is_its_row_in_the_list_joined_to_its_words(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    listing = await runtime.messages("received")
    row = next(item for item in listing.value.messages if item.id == WITH_FILE)

    found = (await runtime.message("received", WITH_FILE)).value

    assert found.model_dump(include=set(MessageSummary.model_fields)) == row.model_dump()
    assert found.sent_at.isoformat() == "2026-10-14T17:40:00+02:00"
    assert found.body.text.startswith("Adjuntamos la autorización")
    assert [attachment.name for attachment in found.attachments] == ["Autorización museo.pdf"]


async def test_a_message_is_found_by_its_id_in_any_letter_case(harness: Harness) -> None:
    runtime = harness.registry().get("marta")

    found = await runtime.message("received", WITH_FILE.upper())

    assert found.value.id == WITH_FILE


async def test_a_message_the_family_sent_is_read_from_the_sent_folder(harness: Harness) -> None:
    runtime = harness.registry().get("marta")

    found = await runtime.message("sent", synthetic_guid(0x2001))

    assert found.value.subject == "Ausencia de Lucía"
    assert found.value.body.text.startswith("Ausencia de Lucía.")


async def test_a_message_is_stored_after_it_is_read_and_read_again_when_its_time_is_up(
    harness: Harness, clock: ManualClock
) -> None:
    settings = harness.settings(cache=CacheTtls(messages=100_000, message=60))
    runtime = harness.registry(settings).get("marta")
    first = await runtime.message("received", UNREAD)
    reads = harness.requests_to(MESSAGE_DATA)

    clock.advance(59)
    second = await runtime.message("received", UNREAD)
    clock.advance(1)
    third = await runtime.message("received", UNREAD)

    assert [answer.status for answer in (first, second, third)] == ["miss", "hit", "miss"]
    assert 59 <= second.age < 60
    assert harness.requests_to(MESSAGE_DATA) == reads + 1


async def test_a_time_to_live_of_zero_turns_the_store_of_messages_off(harness: Harness) -> None:
    runtime = harness.registry(harness.settings(cache=CacheTtls(message=0))).get("marta")

    await runtime.message("received", UNREAD)
    await runtime.message("received", UNREAD)

    assert harness.requests_to(MESSAGE_DATA) == 2


@pytest.mark.parametrize(
    "reference",
    ["", "message", "5afe0000-0000-4000-8000-00000000100", f"{UNREAD}0", f" {UNREAD}"],
)
async def test_what_is_no_message_id_is_not_found_without_asking_the_portal(
    harness: Harness, reference: str
) -> None:
    runtime = harness.registry().get("marta")

    with pytest.raises(NotFoundError) as raised:
        await runtime.message("received", reference)

    assert (raised.value.kind, raised.value.reference) == ("message", reference)
    assert len(harness.sim.requests) == 0


async def test_a_message_the_list_does_not_hold_is_not_found_and_its_page_is_never_opened(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    unknown = synthetic_guid(0x9999)

    with pytest.raises(NotFoundError) as raised:
        await runtime.message("received", unknown)

    assert (raised.value.kind, raised.value.reference) == ("message", unknown)
    assert harness.requests_to("Comunicado.aspx") == 0
    assert harness.requests_to(MESSAGE_DATA) == 0


@pytest.mark.parametrize(("folder", "number"), [("sent", 0x1001), ("received", 0x2001)])
async def test_a_message_is_found_only_in_the_folder_it_is_in(
    harness: Harness, folder: FolderName, number: int
) -> None:
    runtime = harness.registry().get("marta")

    with pytest.raises(NotFoundError):
        await runtime.message(folder, synthetic_guid(number))

    assert harness.requests_to(MESSAGE_DATA) == 0


async def test_an_account_cannot_read_a_message_of_another_account(harness: Harness) -> None:
    registry = harness.registry()
    theirs = synthetic_guid(0x1101)

    assert (await registry.get("pablo").message("received", theirs)).value.id == theirs
    with pytest.raises(NotFoundError):
        await registry.get("marta").message("received", theirs)


async def test_a_fresh_look_reads_the_list_and_the_words_again(harness: Harness) -> None:
    runtime = harness.registry().get("marta")
    await runtime.message("received", UNREAD)
    lists, pages = harness.requests_to("Comunicados.aspx"), harness.requests_to(MESSAGE_DATA)

    again = await runtime.message("received", UNREAD, fresh=True)

    assert again.status == "bypass"
    assert harness.requests_to("Comunicados.aspx") > lists
    assert harness.requests_to(MESSAGE_DATA) == pages + 1


async def test_a_message_that_arrived_since_is_found_only_after_a_fresh_look(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    await runtime.messages("received")
    harness.deliver(DEMO_USER_A, A_NEW_MESSAGE)

    with pytest.raises(NotFoundError):
        await runtime.message("received", A_NEW_MESSAGE.guid)
    found = await runtime.message("received", A_NEW_MESSAGE.guid, fresh=True)

    assert found.value.subject == "Nuevo aviso"


async def test_the_row_is_the_list_as_it_is_now_even_when_the_words_are_older(
    harness: Harness, clock: ManualClock
) -> None:
    runtime = harness.registry().get("marta")
    first = await runtime.message("received", UNREAD)
    reads = harness.requests_to(MESSAGE_DATA)
    harness.revise(DEMO_USER_A, UNREAD, read=True)
    clock.advance(121)

    second = await runtime.message("received", UNREAD)

    assert (first.value.read, second.value.read) == (False, True)
    assert second.value.body == first.value.body
    assert second.status == "miss"
    assert harness.requests_to(MESSAGE_DATA) == reads


async def test_an_account_keeps_the_words_of_only_the_latest_messages_it_read(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alexia_api.services.registry.MAX_CACHED_MESSAGES", 2)
    runtime = harness.registry().get("marta")
    ids = [synthetic_guid(number) for number in (0x1001, 0x1002, 0x1003)]
    for guid in ids:
        await runtime.message("received", guid)

    statuses = [(await runtime.message("received", guid)).status for guid in reversed(ids)]

    assert statuses == ["hit", "hit", "miss"]


async def test_many_requests_for_one_message_share_one_read(harness: Harness) -> None:
    runtime = harness.registry().get("marta")

    answers = await asyncio.gather(*(runtime.message("received", UNREAD) for _ in range(8)))

    assert {answer.status for answer in answers} == {"miss"}
    assert harness.requests_to(MESSAGE_DATA) == 1


@pytest.mark.parametrize(
    ("zone", "offset"), [("Europe/Madrid", "+02:00"), ("Asia/Tokyo", "+09:00")]
)
async def test_the_time_a_message_was_sent_is_wall_time_in_the_school_zone(
    harness: Harness, zone: str, offset: str
) -> None:
    runtime = harness.registry(harness.settings(timezone=zone)).get("marta")

    found = await runtime.message("received", WITH_FILE)

    assert found.value.sent_at.isoformat() == f"2026-10-14T17:40:00{offset}"


async def test_a_blocked_account_does_not_stop_the_other_account(
    harness: Harness, failure: Failure
) -> None:
    settings = harness.settings(
        accounts={
            "marta": harness.account_settings(password="not-her-password"),
            "pablo": harness.account_settings(DEMO_USER_B, DEMO_PASSWORD_B),
        }
    )
    registry = harness.registry(settings)

    first = await failure(registry.get("marta").directory())
    second = await failure(registry.get("marta").directory())
    pablo = await registry.get("pablo").directory()

    assert isinstance(first, InvalidCredentials)
    assert isinstance(second, BreakerOpen)
    assert [child.slug for child in pablo.value.children] == ["hugo", "alba"]
    assert harness.requests_to("/Validar") == 2
    assert isinstance((await registry.get("marta").status()).connection, Blocked)
    assert isinstance((await registry.get("pablo").status()).connection, LoggedIn)


async def test_a_block_is_kept_in_the_state_directory_under_the_account_name(
    harness: Harness, failure: Failure
) -> None:
    settings = harness.settings(
        accounts={"marta": harness.account_settings(password="not-her-password")}
    )
    await failure(harness.registry(settings).get("marta").directory())

    assert (harness.state_dir / "breaker" / "marta.json").is_file()


async def test_a_block_left_by_an_earlier_run_is_respected_at_startup(
    harness: Harness, clock: ManualClock, failure: Failure
) -> None:
    settings = harness.settings(
        accounts={"marta": harness.account_settings(password="not-her-password")}
    )
    await failure(harness.registry(settings).get("marta").directory())
    logins = harness.requests_to("/Validar")

    restarted = harness.registry(settings)
    detail = await failure(restarted.get("marta").directory())

    assert isinstance(detail, BreakerOpen)
    assert harness.requests_to("/Validar") == logins
    assert isinstance((await restarted.get("marta").status()).connection, Blocked)
    assert BreakerStore(harness.state_dir / "breaker", clock).read(parse_account_id("marta"))


async def test_resetting_a_block_lets_the_next_request_try_the_portal_again(
    harness: Harness, failure: Failure
) -> None:
    settings = harness.settings(
        accounts={"marta": harness.account_settings(password="not-her-password")}
    )
    runtime = harness.registry(settings).get("marta")
    await failure(runtime.directory())

    assert await runtime.reset_block() is True
    assert await runtime.reset_block() is False
    detail = await failure(runtime.directory())

    assert isinstance(detail, InvalidCredentials)
    assert harness.requests_to("/Validar") == 2


async def test_status_describes_the_account_without_calling_the_portal(harness: Harness) -> None:
    settings = harness.settings(
        accounts={"marta": harness.account_settings(label="Marta's account")}
    )
    runtime = harness.registry(settings).get("marta")

    before = await runtime.status()

    assert isinstance(before.connection, LoggedOut)
    assert before.child_count is None
    assert before.id == "marta"
    assert before.label == "Marta's account"
    assert before.portal_host == "sim.invalid"
    assert before.capabilities == Capabilities(writes=False, forms=False, restore_unread=False)
    assert harness.sim.requests == []


async def test_status_after_a_login_shows_the_session_and_the_children_seen(
    harness: Harness,
) -> None:
    runtime = harness.registry().get("marta")
    await runtime.directory()
    calls = len(harness.sim.requests)

    after = await runtime.status()

    assert isinstance(after.connection, LoggedIn)
    assert after.child_count == 2
    assert after.label == "marta"
    assert len(harness.sim.requests) == calls


@pytest.mark.parametrize(("zone", "hours"), [("Europe/Madrid", 1), ("Asia/Tokyo", 9)])
async def test_times_the_server_makes_carry_the_offset_of_the_school_zone(
    harness: Harness, zone: str, hours: int
) -> None:
    runtime = harness.registry(harness.settings(timezone=zone)).get("marta")
    await runtime.directory()

    connection = (await runtime.status()).connection

    assert isinstance(connection, LoggedIn)
    assert connection.since.utcoffset() == timedelta(hours=hours)
    assert connection.last_success_at.utcoffset() == timedelta(hours=hours)


async def test_the_operator_switches_show_in_the_status(harness: Harness) -> None:
    settings = harness.settings(allow_writes=True, allow_forms=True, restore_unread=True)

    status = await harness.registry(settings).get("marta").status()

    assert status.capabilities == Capabilities(writes=True, forms=True, restore_unread=True)


async def test_a_check_logs_in_and_says_whether_the_session_was_new(harness: Harness) -> None:
    runtime = harness.registry().get("marta")

    first = await runtime.check()
    second = await runtime.check()

    assert (first.session, first.child_count) == ("new", 2)
    assert second.session == "reused"


async def test_secrets_can_be_read_from_the_environment(harness: Harness) -> None:
    settings = harness.settings(
        accounts={
            "marta": harness.account_settings("env:MARTA_USER", "env:MARTA_PASSWORD"),
        }
    )
    registry = harness.registry(
        settings,
        environ={"MARTA_USER": "marta.ejemplo", "MARTA_PASSWORD": "demo-password-a"},
    )

    directory = (await registry.get("marta").directory()).value

    assert [child.slug for child in directory.children] == ["lucia", "mateo"]


async def test_a_secret_that_is_not_set_stops_the_build_before_anything_connects(
    harness: Harness,
) -> None:
    settings = harness.settings(
        accounts={
            "marta": harness.account_settings(),
            "pablo": harness.account_settings(DEMO_USER_B, "env:PABLO_PASSWORD"),
        }
    )

    with pytest.raises(ConfigError, match=r"accounts\.pablo\.password.*PABLO_PASSWORD"):
        Registry.build(settings, environ={}, clock=harness.clock)

    assert harness.sim.requests == []


async def test_only_the_accounts_a_key_may_use_are_visible_to_it(harness: Harness) -> None:
    registry = harness.registry()
    only_pablo = Principal(
        key_name="pablo-only", scopes=frozenset({"read"}), accounts=frozenset({"pablo"})
    )
    everything = Principal(
        key_name="everything", scopes=frozenset({"read"}), accounts=frozenset({"*"})
    )

    assert [runtime.account for runtime in registry.visible_to(only_pablo)] == ["pablo"]
    assert [runtime.account for runtime in registry.visible_to(everything)] == ["marta", "pablo"]


async def test_closing_the_registry_twice_is_harmless(harness: Harness) -> None:
    registry = harness.registry()

    await registry.aclose()
    await registry.aclose()
