from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from icalendar import Event

from alexia_api.sim.agenda import LessonEdit, SimOccasion, SimSlot
from alexia_api.sim.world import DEMO_USER_A, default_world, synthetic_guid
from tests.api.support import (
    CALENDAR_MEDIA_TYPE,
    Api,
    MakeApi,
    problem_of,
    unfolded,
    vevents,
)
from tests.harness import A_NEW_SIBLING, Harness

MADRID = ZoneInfo("Europe/Madrid")
ACCOUNT = "/v1/accounts/marta"
LUCIA = f"{ACCOUNT}/children/lucia/agenda.ics"
MATEO = f"{ACCOUNT}/children/mateo/agenda.ics"
GUARDIAN = f"{ACCOUNT}/guardian/agenda.ics"
FAMILY = f"{ACCOUNT}/agenda.ics"
FEED_ROUTES = [LUCIA, GUARDIAN, FAMILY]
TODAY = date(2026, 1, 1)
FEED = "ControladorAgenda.ashx"
LESSONS_A_DAY = 6
NAVIDAD = "VACACIONES DE NAVIDAD"
PASCUA = "ESCUELA DE PASCUA"


def school_days(first: date, last: date) -> int:
    days = (first + timedelta(days=offset) for offset in range((last - first).days + 1))
    return sum(1 for day in days if day.weekday() < 5)


def is_lesson(event: Event) -> bool:
    return str(event.get("DESCRIPTION", "")).startswith("Teacher")


def summaries(events: list[Event]) -> list[str]:
    return [str(event["SUMMARY"]) for event in events]


def only(events: list[Event], summary: str) -> Event:
    [found] = [event for event in events if str(event["SUMMARY"]) == summary]
    return found


async def calendar(api: Api, path: str, **params: Any) -> list[Event]:
    response = await api.get(path, params=params)
    assert response.status_code == 200, response.text
    return vevents(response.content)


def thursday_slot() -> SimSlot:
    timetable = default_world().families[0].children[0].timetable
    return next(slot for slot in timetable if slot.weekday == 4)


async def test_a_child_calendar_is_a_file_a_calendar_app_can_subscribe_to(api: Api) -> None:
    response = await api.get(LUCIA)
    assert response.status_code == 200
    assert response.headers["content-type"] == CALENDAR_MEDIA_TYPE
    assert response.headers["x-cache"] == "miss"
    lines = unfolded(response.content)
    assert lines[0] == "BEGIN:VCALENDAR"
    assert "X-WR-CALNAME:Lucía school calendar" in lines
    assert "X-WR-TIMEZONE:Europe/Madrid" in lines


async def test_a_child_calendar_reaches_two_weeks_back_and_half_a_year_ahead(api: Api) -> None:
    events = await calendar(api, LUCIA)
    first, last = TODAY - timedelta(days=14), TODAY + timedelta(days=90)
    lessons = [event for event in events if is_lesson(event)]
    assert len(lessons) == school_days(first, last) * LESSONS_A_DAY
    others = Counter(str(event["SUMMARY"]) for event in events if not is_lesson(event))
    assert others == {NAVIDAD: 1, PASCUA: 1}


@pytest.mark.parametrize(
    ("lessons_ahead", "last_lesson_day"),
    [(0, TODAY), (7, TODAY + timedelta(days=7)), (90, TODAY + timedelta(days=90))],
)
async def test_lessons_stop_sooner_than_the_rest_of_the_calendar(
    api: Api, lessons_ahead: int, last_lesson_day: date
) -> None:
    events = await calendar(api, LUCIA, lessons_ahead=lessons_ahead)
    lessons = [event for event in events if is_lesson(event)]
    first = TODAY - timedelta(days=14)
    assert len(lessons) == school_days(first, last_lesson_day) * LESSONS_A_DAY
    assert max(event.decoded("DTSTART").date() for event in lessons) <= last_lesson_day
    assert {NAVIDAD, PASCUA} <= set(summaries(events))


async def test_the_family_calendar_stops_the_lessons_of_every_child_on_the_same_day(
    api: Api,
) -> None:
    events = await calendar(api, FAMILY, lessons_ahead=7)
    lessons = [event for event in events if is_lesson(event)]
    last_lesson_day = TODAY + timedelta(days=7)
    first = TODAY - timedelta(days=14)
    assert len(lessons) == 2 * school_days(first, last_lesson_day) * LESSONS_A_DAY
    assert max(event.decoded("DTSTART").date() for event in lessons) <= last_lesson_day
    assert {NAVIDAD, PASCUA} <= set(summaries(events))


@pytest.mark.parametrize(("ahead", "has_easter"), [(80, False), (88, True), (100, True)])
async def test_ahead_sets_how_far_the_calendar_reaches(
    api: Api, ahead: int, has_easter: bool
) -> None:
    events = await calendar(api, LUCIA, ahead=ahead)
    assert (PASCUA in summaries(events)) is has_easter


async def test_a_reach_of_nothing_makes_a_calendar_of_today(api: Api) -> None:
    events = await calendar(api, LUCIA, back=0, ahead=0)
    assert len([event for event in events if is_lesson(event)]) == LESSONS_A_DAY
    others = Counter(str(event["SUMMARY"]) for event in events if not is_lesson(event))
    assert others == {NAVIDAD: 1}


async def test_back_sets_how_far_the_calendar_reaches_into_the_past(api: Api) -> None:
    short = await calendar(api, LUCIA, back=0, ahead=0)
    long = await calendar(api, LUCIA, back=100, ahead=0)
    assert len(long) > len(short)
    assert summaries([event for event in long if not is_lesson(event)]).count("FESTIVO") == 2


async def test_a_holiday_is_free_time_whichever_way_the_portal_ends_it(api: Api) -> None:
    events = await calendar(api, LUCIA, back=100, ahead=0)
    holidays = sorted(
        (event for event in events if str(event["SUMMARY"]) == "FESTIVO"),
        key=lambda event: event.decoded("DTSTART"),
    )
    assert [(event.decoded("DTSTART"), event.decoded("DTEND")) for event in holidays] == [
        (date(2025, 10, 12), date(2025, 10, 13)),
        (date(2025, 12, 8), date(2025, 12, 9)),
    ]
    assert {str(event["TRANSP"]) for event in holidays} == {"TRANSPARENT"}


async def test_the_holidays_that_last_weeks_end_on_their_last_day(api: Api) -> None:
    holiday = only(await calendar(api, LUCIA), NAVIDAD)
    assert holiday.decoded("DTSTART") == date(2025, 12, 23)
    assert holiday.decoded("DTEND") == date(2026, 1, 8)


async def test_an_event_that_lasts_days_but_has_hours_keeps_its_hours(api: Api) -> None:
    school = only(await calendar(api, LUCIA), PASCUA)
    assert school.decoded("DTSTART") == datetime(2026, 3, 30, 9, 0, tzinfo=MADRID)
    assert school.decoded("DTEND") == datetime(2026, 4, 2, 17, 0, tzinfo=MADRID)
    assert "TRANSP" not in school


async def test_a_lesson_has_its_time_its_teacher_and_a_stable_id(api: Api) -> None:
    events = await calendar(api, LUCIA, back=0, ahead=0)
    slot = thursday_slot()
    first = next(event for event in events if is_lesson(event))
    assert str(first["SUMMARY"]) == slot.title
    assert str(first["DESCRIPTION"]) == f"Teacher {slot.teacher}."
    assert first.decoded("DTSTART") == datetime(2026, 1, 1, 9, 0, tzinfo=MADRID)
    assert first.decoded("DTEND") == datetime(2026, 1, 1, 9, 45, tzinfo=MADRID)
    assert str(first["UID"]) == f"{synthetic_guid(0x201)}.{slot.id}|2026-01-01@alexia-familia-api"
    assert first.decoded("DTSTAMP") == api.harness.clock.now().replace(microsecond=0)


async def test_what_the_school_flags_on_a_lesson_is_told_in_its_description(api: Api) -> None:
    api.harness.sim.edit_lesson(
        synthetic_guid(0x201),
        thursday_slot().id,
        TODAY,
        LessonEdit(
            teacher="Profesora invitada",
            counters={"tareas": "2", "actividades": True, "anotaciones": 1, "is_sustitucion": True},
        ),
    )
    events = await calendar(api, LUCIA, back=0, ahead=0)
    first = next(event for event in events if is_lesson(event))
    assert str(first["DESCRIPTION"]) == (
        "Teacher Profesora invitada.\n"
        "The school flagged 2 tasks, 1 activity and 1 note.\n"
        "A substitute teacher takes this lesson."
    )


async def test_words_of_the_school_cannot_break_the_file(api: Api) -> None:
    hostile = "Mates\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nSUMMARY:pwned"
    api.harness.sim.edit_lesson(
        synthetic_guid(0x201), thursday_slot().id, TODAY, LessonEdit(title=hostile)
    )
    response = await api.get(LUCIA, params={"back": 0, "ahead": 0})
    events = vevents(response.content)
    assert len(events) == LESSONS_A_DAY + 1
    assert "pwned" not in summaries(events)
    assert unfolded(response.content).count("BEGIN:VEVENT") == LESSONS_A_DAY + 1
    assert "Mates END:VEVENT BEGIN:VEVENT SUMMARY:pwned" in summaries(events)


async def test_the_stamp_is_the_time_of_the_request_and_the_ids_do_not_change(api: Api) -> None:
    first = await api.get(LUCIA)
    first_stamp = api.harness.clock.now()
    api.harness.clock.advance(30)
    second = await api.get(LUCIA)
    second_stamp = api.harness.clock.now()
    assert second.headers["x-cache"] == "hit"
    assert second_stamp - first_stamp == timedelta(seconds=30)
    assert f"DTSTAMP:{first_stamp:%Y%m%dT%H%M%SZ}" in unfolded(first.content)
    assert f"DTSTAMP:{second_stamp:%Y%m%dT%H%M%SZ}" in unfolded(second.content)
    ids = {str(event["UID"]) for response in (first, second) for event in vevents(response.content)}
    assert len(ids) == len(vevents(first.content))


async def test_the_second_fetch_comes_from_the_cache_and_says_how_old_it_is(api: Api) -> None:
    first = await api.get(LUCIA)
    api.harness.clock.advance(30)
    second = await api.get(LUCIA)
    assert (first.headers["x-cache"], first.headers["age"]) == ("miss", "0")
    assert (second.headers["x-cache"], second.headers["age"]) == ("hit", "30")
    assert api.harness.requests_to(FEED) == 1


async def test_a_feed_cannot_force_the_portal_to_be_read_again(api: Api) -> None:
    await api.get(LUCIA)
    reads = api.harness.requests_to(FEED)
    forced = await api.get(f"{LUCIA}?fresh=true")
    assert forced.status_code == 200
    assert forced.headers["x-cache"] == "hit"
    assert api.harness.requests_to(FEED) == reads


async def test_the_calendar_of_a_child_shares_its_read_with_the_agenda_of_the_same_days(
    api: Api,
) -> None:
    await api.get(LUCIA)
    first, last = TODAY - timedelta(days=14), TODAY + timedelta(days=180)
    shared = await api.get(f"{ACCOUNT}/children/lucia/agenda?from={first}&to={last}")
    assert shared.headers["x-cache"] == "hit"
    assert api.harness.requests_to(FEED) == 1


@pytest.mark.parametrize(
    "query",
    [
        "back=-1",
        "back=367",
        "ahead=-1",
        "ahead=367",
        "lessons_ahead=-1",
        "lessons_ahead=367",
        "back=x",
    ],
)
async def test_a_reach_the_server_does_not_allow_is_refused(api: Api, query: str) -> None:
    response = await api.get(f"{LUCIA}?{query}")
    problem_of(response, status=422, code="validation_error")
    assert api.harness.requests_to(FEED) == 0


@pytest.mark.parametrize("query", ["back=366", "ahead=366", "lessons_ahead=366", "back=0&ahead=0"])
async def test_the_longest_and_the_shortest_reach_are_read(api: Api, query: str) -> None:
    assert (await api.get(f"{LUCIA}?{query}")).status_code == 200


async def test_each_child_has_the_lessons_of_its_own_timetable(api: Api) -> None:
    lucia = await calendar(api, LUCIA, back=0, ahead=0)
    mateo = await calendar(api, MATEO, back=0, ahead=0)
    lucia_titles = [str(event["SUMMARY"]) for event in lucia if is_lesson(event)]
    mateo_titles = [str(event["SUMMARY"]) for event in mateo if is_lesson(event)]
    assert lucia_titles != mateo_titles


async def test_a_child_calendar_names_the_child(api: Api) -> None:
    lines = unfolded((await api.get(MATEO)).content)
    assert "X-WR-CALNAME:Mateo school calendar" in lines


async def test_an_unknown_child_has_no_calendar(api: Api) -> None:
    response = await api.get(f"{ACCOUNT}/children/ghost/agenda.ics")
    problem_of(response, status=404, code="child_not_found")


async def test_the_guardian_calendar_has_the_interviews_and_the_school_events(api: Api) -> None:
    response = await api.get(GUARDIAN, params={"back": 80, "ahead": 0})
    assert "X-WR-CALNAME:marta school meetings" in unfolded(response.content)
    events = vevents(response.content)
    assert sorted(summaries(events)) == sorted(["Entrevista: Aceptada", "FESTIVO", NAVIDAD])
    interview = only(events, "Entrevista: Aceptada")
    assert interview.decoded("DTSTART") == datetime(2025, 10, 20, 16, 0, tzinfo=MADRID)
    assert interview.decoded("DTEND") == datetime(2025, 10, 20, 16, 30, tzinfo=MADRID)
    assert "DESCRIPTION" not in interview
    assert str(interview["UID"]) == f"marta.{synthetic_guid(0x7301)}|2025-10-20@alexia-familia-api"


async def test_a_login_without_a_guardian_has_no_guardian_calendar(api: Api) -> None:
    api.harness.sim.options.home_without_guardian = True
    problem_of(await api.get(GUARDIAN), status=404, code="guardian_not_found")


async def test_the_family_calendar_names_the_account(api: Api) -> None:
    lines = unfolded((await api.get(FAMILY)).content)
    assert "X-WR-CALNAME:marta family school calendar" in lines


async def test_the_family_calendar_puts_the_name_of_each_child_before_each_of_their_entries(
    api: Api,
) -> None:
    events = await calendar(api, FAMILY, back=80, ahead=0)
    days = school_days(TODAY - timedelta(days=80), TODAY) * LESSONS_A_DAY
    assert len(events) == 2 * days + 5
    lessons = [str(event["SUMMARY"]) for event in events if is_lesson(event)]
    assert sum(summary.startswith("Lucía: ") for summary in lessons) == days
    assert sum(summary.startswith("Mateo: ") for summary in lessons) == days
    assert "Lucía: EXCURSIÓN AL MUSEO" in summaries(events)
    assert "Mateo: SALIDA A LA GRANJA" in summaries(events)


async def test_what_the_whole_school_shares_appears_once_and_belongs_to_nobody(api: Api) -> None:
    events = await calendar(api, FAMILY, back=80, ahead=0)
    shared = [text for text in summaries(events) if "FESTIVO" in text or NAVIDAD in text]
    assert shared == ["FESTIVO", NAVIDAD]


async def test_the_guardian_interviews_are_in_the_family_calendar_without_a_name(api: Api) -> None:
    events = await calendar(api, FAMILY, back=80, ahead=0)
    interview = only(events, "Entrevista: Aceptada")
    assert interview.decoded("DTSTART") == datetime(2025, 10, 20, 16, 0, tzinfo=MADRID)


async def test_every_entry_of_the_family_calendar_has_an_id_of_its_own(api: Api) -> None:
    events = await calendar(api, FAMILY, back=80, ahead=0)
    ids = [str(event["UID"]) for event in events]
    assert len(set(ids)) == len(ids)


async def test_the_id_of_a_lesson_is_the_same_in_the_family_calendar_and_the_child_calendar(
    api: Api,
) -> None:
    own = await calendar(api, LUCIA, back=0, ahead=0)
    family = {str(event["UID"]) for event in await calendar(api, FAMILY, back=0, ahead=0)}
    lessons = {str(event["UID"]) for event in own if is_lesson(event)}
    assert len(lessons) == LESSONS_A_DAY
    assert lessons <= family


async def test_what_the_family_shares_gets_an_id_that_names_the_account(api: Api) -> None:
    events = await calendar(api, FAMILY, back=80, ahead=0)
    assert str(only(events, NAVIDAD)["UID"]) == (
        f"marta.{synthetic_guid(0x7102)}|2025-12-23@alexia-familia-api"
    )


async def test_the_family_calendar_without_a_guardian_has_the_children_only(api: Api) -> None:
    api.harness.sim.options.home_without_guardian = True
    events = await calendar(api, FAMILY, back=80, ahead=0)
    assert "Entrevista: Aceptada" not in summaries(events)
    assert "Lucía: EXCURSIÓN AL MUSEO" in summaries(events)


async def test_the_family_calendar_reads_each_child_and_the_guardian_once(api: Api) -> None:
    first = await api.get(FAMILY)
    api.harness.clock.advance(30)
    second = await api.get(FAMILY)
    assert (first.headers["x-cache"], first.headers["age"]) == ("miss", "0")
    assert (second.headers["x-cache"], second.headers["age"]) == ("hit", "30")
    assert api.harness.requests_to(FEED) == 3


async def test_a_family_calendar_that_was_partly_stored_is_a_miss(api: Api) -> None:
    await api.get(LUCIA)
    response = await api.get(FAMILY)
    assert response.headers["x-cache"] == "miss"
    assert api.harness.requests_to(FEED) == 3


async def test_two_children_with_the_same_first_name_are_told_apart_by_their_slugs(
    api: Api,
) -> None:
    twin = replace(
        A_NEW_SIBLING,
        full_name="Lucía Otra Muestra",
        first_name="Lucía",
        events=(
            SimOccasion(
                id=synthetic_guid(0x7251),
                title="TALLER",
                first=(12, 15),
                last=(12, 15),
                starts="10:00",
                ends="11:00",
            ),
        ),
    )
    api.harness.enrol(DEMO_USER_A, twin)
    texts = summaries(await calendar(api, FAMILY, back=30, ahead=0))
    assert "Lucía (lucia-2): TALLER" in texts
    assert any(text.startswith("Lucía (lucia): ") for text in texts)
    assert any(text.startswith("Mateo: ") for text in texts)
    assert not any(text.startswith("Lucía: ") for text in texts)


async def test_a_family_calendar_is_all_or_nothing(api: Api) -> None:
    await api.get(LUCIA)
    api.harness.sim.options.agenda_feed_fails = True
    response = await api.get(FAMILY)
    problem_of(response, status=502, code="unexpected_reply")
    assert not response.content.startswith(b"BEGIN:VCALENDAR")


@pytest.mark.parametrize("path", FEED_ROUTES)
async def test_a_feed_the_portal_changed_is_a_problem_and_never_a_shorter_calendar(
    api: Api, path: str
) -> None:
    api.harness.sim.options.agenda_bad_event = True
    response = await api.get(path)
    problem_of(response, status=502, code="portal_changed")
    assert response.headers["content-type"] == "application/problem+json"


@pytest.mark.parametrize("path", FEED_ROUTES)
async def test_a_calendar_is_made_again_after_a_failure(api: Api, path: str) -> None:
    api.harness.sim.options.agenda_feed_fails = True
    problem_of(await api.get(path), status=502, code="unexpected_reply")
    api.harness.sim.options.agenda_feed_fails = False
    assert (await api.get(path)).status_code == 200


@pytest.mark.parametrize("path", [*FEED_ROUTES, MATEO])
async def test_every_calendar_route_says_503_for_a_blocked_account(
    make_api: MakeApi, harness: Harness, path: str
) -> None:
    api = await make_api(accounts={"marta": harness.account_settings(password="not-the-password")})
    await api.post(f"{ACCOUNT}/connection/check")
    problem_of(await api.get(path), status=503, code="breaker_open")
    assert api.harness.sim.counters.login_attempts == 1


async def test_each_account_has_its_own_family_calendar(api: Api) -> None:
    marta = summaries(await calendar(api, FAMILY, back=80, ahead=0))
    pablo = summaries(await calendar(api, "/v1/accounts/pablo/agenda.ics", back=80, ahead=0))
    assert any(text.startswith("Lucía: ") for text in marta)
    assert not any(text.startswith("Hugo: ") for text in marta)
    assert any(text.startswith("Hugo: ") for text in pablo)
    assert any(text.startswith("Alba: ") for text in pablo)
