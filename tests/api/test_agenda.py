import asyncio
from collections import Counter
from datetime import date, timedelta
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from alexia_api.api.errors import ApiError
from alexia_api.api.routers.agenda import resolve_window
from alexia_api.domain.agenda import EVENT_KINDS
from alexia_api.sim.agenda import LessonEdit, SimSlot
from alexia_api.sim.world import default_world, synthetic_guid
from tests.api.support import Api, MakeApi, problem_of
from tests.harness import Harness

ACCOUNT = "/v1/accounts/marta"
LUCIA = f"{ACCOUNT}/children/lucia/agenda"
MATEO = f"{ACCOUNT}/children/mateo/agenda"
GUARDIAN = f"{ACCOUNT}/guardian/agenda"
TODAY = date(2026, 1, 1)
FEED = "ControladorAgenda.ashx"
HOME = "HomeMetro.aspx"


def timetable_of(child: int) -> tuple[SimSlot, ...]:
    return default_world().families[0].children[child].timetable


def thursday_slot() -> SimSlot:
    return next(slot for slot in timetable_of(0) if slot.weekday == 4)


def kinds_of(response_body: dict[str, Any]) -> Counter[str]:
    return Counter(item["kind"] for item in response_body["items"])


def lessons_of(response_body: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in response_body["items"] if item["kind"] == "lesson"]


async def test_without_a_range_the_agenda_is_the_week_that_starts_today(api: Api) -> None:
    response = await api.get(LUCIA)
    assert response.status_code == 200
    body = response.json()
    assert (body["from"], body["to"]) == ("2026-01-01", "2026-01-07")
    assert kinds_of(body) == {"lesson": 30, "school_event": 1}


async def test_the_days_asked_for_are_echoed_back(api: Api) -> None:
    body = (await api.get(f"{LUCIA}?from=2025-12-08&to=2025-12-10")).json()
    assert (body["from"], body["to"]) == ("2025-12-08", "2025-12-10")


async def test_a_range_without_an_end_is_a_week_from_its_start(api: Api) -> None:
    body = (await api.get(f"{LUCIA}?from=2025-12-08")).json()
    assert (body["from"], body["to"]) == ("2025-12-08", "2025-12-14")


async def test_a_range_without_a_start_begins_today(api: Api) -> None:
    body = (await api.get(f"{LUCIA}?to=2026-01-03")).json()
    assert (body["from"], body["to"]) == ("2026-01-01", "2026-01-03")


async def test_a_lesson_names_its_teacher_and_the_time_it_takes_place(api: Api) -> None:
    body = (await api.get(f"{LUCIA}?from=2026-01-01&to=2026-01-01")).json()
    slot = thursday_slot()
    assert lessons_of(body)[0] == {
        "id": f"{slot.id}|2026-01-01",
        "kind": "lesson",
        "title": slot.title,
        "teacher": slot.teacher,
        "starts_at": "2026-01-01T09:00:00+01:00",
        "ends_at": "2026-01-01T09:45:00+01:00",
        "all_day": False,
        "signals": {"tasks": 0, "activities": 0, "notes": 0, "tests": 0, "substitution": False},
    }


async def test_the_lessons_of_a_day_come_in_the_order_of_the_bell(api: Api) -> None:
    body = (await api.get(f"{LUCIA}?from=2026-01-02&to=2026-01-02")).json()
    starts = [lesson["starts_at"][11:16] for lesson in lessons_of(body)]
    assert starts == ["09:00", "09:45", "11:00", "11:45", "15:00", "15:45"]


async def test_the_entries_come_earliest_first(api: Api) -> None:
    items = (await api.get(LUCIA)).json()["items"]
    assert [item["starts_at"] for item in items] == sorted(item["starts_at"] for item in items)
    assert items[0]["title"] == "VACACIONES DE NAVIDAD"


async def test_a_school_event_that_lasts_days_is_listed_with_its_whole_span(api: Api) -> None:
    items = (await api.get(f"{LUCIA}?from=2026-01-05&to=2026-01-05&kind=school_event")).json()[
        "items"
    ]
    assert items == [
        {
            "id": f"{synthetic_guid(0x7102)}|2025-12-23",
            "kind": "school_event",
            "title": "VACACIONES DE NAVIDAD",
            "teacher": None,
            "starts_at": "2025-12-23T00:00:00+01:00",
            "ends_at": "2026-01-07T23:59:00+01:00",
            "all_day": True,
            "signals": None,
        }
    ]


async def test_what_the_school_flags_on_a_lesson_is_counted(api: Api) -> None:
    api.harness.sim.edit_lesson(
        synthetic_guid(0x201),
        thursday_slot().id,
        TODAY,
        LessonEdit(
            teacher="Profesora invitada",
            counters={
                "tareas": "2",
                "actividades": True,
                "anotaciones": 1,
                "controles": "0",
                "is_sustitucion": True,
            },
        ),
    )
    body = (await api.get(f"{LUCIA}?from=2026-01-01&to=2026-01-01")).json()
    first = lessons_of(body)[0]
    assert first["teacher"] == "Profesora invitada"
    assert first["signals"] == {
        "tasks": 2,
        "activities": 1,
        "notes": 1,
        "tests": 0,
        "substitution": True,
    }


async def test_a_lesson_the_school_cancelled_is_not_listed(api: Api) -> None:
    api.harness.sim.cancel_lesson(synthetic_guid(0x201), thursday_slot().id, TODAY)
    body = (await api.get(f"{LUCIA}?from=2026-01-01&to=2026-01-01")).json()
    assert len(lessons_of(body)) == 5
    assert thursday_slot().id not in {lesson["id"].split("|")[0] for lesson in lessons_of(body)}


async def test_a_time_has_the_offset_the_school_has_on_that_day(api: Api) -> None:
    body = (await api.get(f"{LUCIA}?from=2025-10-24&to=2025-10-27")).json()
    starts = {lesson["starts_at"] for lesson in lessons_of(body)}
    assert "2025-10-24T09:00:00+02:00" in starts
    assert "2025-10-27T09:00:00+01:00" in starts


async def test_a_holiday_is_told_from_other_school_events(api: Api) -> None:
    body = (await api.get(f"{LUCIA}?from=2025-12-08&to=2025-12-14")).json()
    assert kinds_of(body) == {"lesson": 30, "holiday": 1}
    [holiday] = [item for item in body["items"] if item["kind"] == "holiday"]
    assert holiday["title"] == "FESTIVO"
    assert holiday["all_day"] is True


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("kind=holiday", {"holiday": 1}),
        ("kind=lesson", {"lesson": 30}),
        ("kind=holiday&kind=lesson", {"holiday": 1, "lesson": 30}),
        ("kind=interview", {}),
    ],
)
async def test_a_kind_keeps_only_the_entries_it_names(
    api: Api, query: str, expected: dict[str, int]
) -> None:
    response = await api.get(f"{LUCIA}?from=2025-12-08&to=2025-12-14&{query}")
    assert response.status_code == 200
    assert kinds_of(response.json()) == expected


async def test_filtering_by_kind_does_not_cost_another_read(api: Api) -> None:
    await api.get(f"{LUCIA}?from=2025-12-08&to=2025-12-14&kind=holiday")
    reads = api.harness.requests_to(FEED)
    everything = await api.get(f"{LUCIA}?from=2025-12-08&to=2025-12-14")
    assert everything.headers["x-cache"] == "hit"
    assert kinds_of(everything.json()) == {"lesson": 30, "holiday": 1}
    assert api.harness.requests_to(FEED) == reads


@pytest.mark.parametrize("kind", ["Lesson", "exam", ""])
async def test_a_kind_the_server_does_not_know_is_refused(api: Api, kind: str) -> None:
    body = problem_of(await api.get(f"{LUCIA}?kind={kind}"), status=422, code="validation_error")
    assert body["errors"][0]["location"][:2] == ["query", "kind"]
    assert api.harness.requests_to(FEED) == 0


@pytest.mark.parametrize("query", ["from=tomorrow", "to=2026-13-01", "from=2026-02-30"])
async def test_a_day_that_is_not_a_date_is_refused_and_no_agenda_is_read(
    api: Api, query: str
) -> None:
    body = problem_of(await api.get(f"{LUCIA}?{query}"), status=422, code="validation_error")
    assert body["errors"][0]["location"][0] == "query"
    assert api.harness.requests_to(FEED) == 0


def days_from_today(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("from=2026-01-05&to=2026-01-04", "to must not be before from"),
        ("to=2025-12-31", "to must not be before from"),
        ("from=2026-01-01&to=2027-01-02", "at most 366 days"),
        (f"from={days_from_today(1101)}", "within 1100 days of today"),
        (f"from={days_from_today(-1101)}", "within 1100 days of today"),
        ("from=0001-01-01", "within 1100 days of today"),
        ("from=9999-12-31", "within 1100 days of today"),
    ],
)
@pytest.mark.parametrize("path", [LUCIA, GUARDIAN])
async def test_a_range_the_server_will_not_read_is_refused_before_the_portal_is_asked(
    api: Api, path: str, query: str, reason: str
) -> None:
    body = problem_of(await api.get(f"{path}?{query}"), status=422, code="invalid_window")
    assert reason in body["detail"]
    assert api.portal_calls() == 0


@pytest.mark.parametrize(
    "query",
    [
        "from=2026-01-01&to=2027-01-01",
        f"from={days_from_today(1100)}",
        f"from={days_from_today(-1100)}&to={days_from_today(-1100)}",
    ],
)
async def test_the_longest_and_the_farthest_ranges_are_read(api: Api, query: str) -> None:
    assert (await api.get(f"{LUCIA}?{query}")).status_code == 200


async def test_a_bad_range_is_told_before_a_missing_child(api: Api) -> None:
    response = await api.get(f"{ACCOUNT}/children/ghost/agenda?from=2026-01-05&to=2026-01-04")
    problem_of(response, status=422, code="invalid_window")
    assert api.portal_calls() == 0


async def test_a_key_is_checked_before_the_range(api: Api) -> None:
    response = await api.client.get(f"{LUCIA}?from=2026-01-05&to=2026-01-04")
    problem_of(response, status=401, code="missing_api_key")


async def test_the_second_read_comes_from_the_cache_and_says_how_old_it_is(api: Api) -> None:
    first = await api.get(LUCIA)
    api.harness.clock.advance(30)
    second = await api.get(LUCIA)
    assert (first.headers["x-cache"], first.headers["age"]) == ("miss", "0")
    assert (second.headers["x-cache"], second.headers["age"]) == ("hit", "30")
    assert second.json() == first.json()
    assert api.harness.requests_to(FEED) == 1


async def test_each_range_is_stored_on_its_own(api: Api) -> None:
    await api.get(f"{LUCIA}?from=2025-12-08")
    await api.get(f"{LUCIA}?from=2025-12-15")
    third = await api.get(f"{LUCIA}?from=2025-12-08")
    assert third.headers["x-cache"] == "hit"
    assert api.harness.requests_to(FEED) == 2


async def test_each_child_is_stored_on_its_own_for_the_same_range(api: Api) -> None:
    lucia = await api.get(LUCIA)
    mateo = await api.get(MATEO)
    assert mateo.headers["x-cache"] == "miss"
    assert [lesson["title"] for lesson in lessons_of(lucia.json())] != [
        lesson["title"] for lesson in lessons_of(mateo.json())
    ]
    assert (await api.get(LUCIA)).headers["x-cache"] == "hit"
    assert (await api.get(MATEO)).headers["x-cache"] == "hit"
    assert api.harness.requests_to(FEED) == 2


async def test_fresh_asks_the_portal_again_and_leaves_the_list_of_children_alone(
    api: Api,
) -> None:
    await api.get(LUCIA)
    lists = api.harness.requests_to(HOME)
    again = await api.get(f"{LUCIA}?fresh=true")
    assert (again.headers["x-cache"], again.headers["age"]) == ("bypass", "0")
    assert api.harness.requests_to(FEED) == 2
    assert api.harness.requests_to(HOME) == lists


async def test_a_stored_agenda_expires_after_its_time(api: Api) -> None:
    await api.get(LUCIA)
    api.harness.clock.advance(601)
    assert (await api.get(LUCIA)).headers["x-cache"] == "miss"


async def test_the_time_an_agenda_is_stored_can_be_set(make_api: MakeApi) -> None:
    api = await make_api(cache={"agenda": 5})
    await api.get(LUCIA)
    api.harness.clock.advance(6)
    assert (await api.get(LUCIA)).headers["x-cache"] == "miss"


async def test_a_change_at_the_school_shows_after_a_fresh_read(api: Api) -> None:
    before = (await api.get(f"{LUCIA}?from=2026-01-01&to=2026-01-01")).json()
    api.harness.sim.cancel_lesson(synthetic_guid(0x201), thursday_slot().id, TODAY)
    stored = (await api.get(f"{LUCIA}?from=2026-01-01&to=2026-01-01")).json()
    after = (await api.get(f"{LUCIA}?from=2026-01-01&to=2026-01-01&fresh=true")).json()
    assert stored == before
    assert len(lessons_of(after)) == len(lessons_of(before)) - 1


async def test_a_child_has_only_the_lessons_of_its_own_timetable(api: Api) -> None:
    lucia = lessons_of((await api.get(LUCIA)).json())
    mateo = lessons_of((await api.get(MATEO)).json())
    assert {lesson["id"].split("|")[0] for lesson in lucia} <= {slot.id for slot in timetable_of(0)}
    assert {lesson["id"].split("|")[0] for lesson in mateo} <= {slot.id for slot in timetable_of(1)}


async def test_the_events_of_one_child_do_not_reach_a_sibling(api: Api) -> None:
    range_ = "from=2025-10-27&to=2025-11-09&kind=school_event"
    lucia = (await api.get(f"{LUCIA}?{range_}")).json()
    mateo = (await api.get(f"{MATEO}?{range_}")).json()
    assert [item["title"] for item in lucia["items"]] == ["EXCURSIÓN AL MUSEO"]
    assert [item["title"] for item in mateo["items"]] == ["SALIDA A LA GRANJA"]


async def test_the_school_events_both_children_share_are_in_each_agenda(api: Api) -> None:
    range_ = "from=2025-12-08&to=2025-12-08&kind=holiday"
    for path in (LUCIA, MATEO):
        items = (await api.get(f"{path}?{range_}")).json()["items"]
        assert [item["title"] for item in items] == ["FESTIVO"]


async def test_agendas_asked_at_once_never_show_a_person_the_agenda_of_another(api: Api) -> None:
    days = [date(2025, 10, 13) + timedelta(days=offset) for offset in range(6)]
    paths = [f"{base}?from={day}&to={day}" for day in days for base in (LUCIA, MATEO, GUARDIAN)]
    responses = await asyncio.gather(*(api.get(path) for path in paths))
    assert {response.status_code for response in responses} == {200}
    slots = {
        LUCIA: {slot.id for slot in timetable_of(0)},
        MATEO: {slot.id for slot in timetable_of(1)},
        GUARDIAN: set(),
    }
    lessons = Counter[str]()
    for path, response in zip(paths, responses, strict=True):
        base = path.split("?")[0]
        ids = {lesson["id"].split("|")[0] for lesson in lessons_of(response.json())}
        assert ids <= slots[base]
        lessons[base] += len(lessons_of(response.json()))
    assert lessons == {LUCIA: 30, MATEO: 30, GUARDIAN: 0}


async def test_an_unknown_child_has_no_agenda(api: Api) -> None:
    problem_of(
        await api.get(f"{ACCOUNT}/children/ghost/agenda"), status=404, code="child_not_found"
    )


async def test_the_child_of_another_account_has_no_agenda_here(api: Api) -> None:
    problem_of(await api.get(f"{ACCOUNT}/children/hugo/agenda"), status=404, code="child_not_found")
    assert (await api.get("/v1/accounts/pablo/children/hugo/agenda")).status_code == 200


async def test_an_unknown_account_has_no_agenda(api: Api) -> None:
    response = await api.get("/v1/accounts/nobody/guardian/agenda")
    problem_of(response, status=404, code="account_not_found")


async def test_the_guardian_agenda_has_the_interviews_and_the_school_events(api: Api) -> None:
    body = (await api.get(f"{GUARDIAN}?from=2025-10-20&to=2025-10-26")).json()
    assert body["items"] == [
        {
            "id": f"{synthetic_guid(0x7301)}|2025-10-20",
            "kind": "interview",
            "title": "Entrevista: Aceptada",
            "teacher": None,
            "starts_at": "2025-10-20T16:00:00+02:00",
            "ends_at": "2025-10-20T16:30:00+02:00",
            "all_day": False,
            "signals": None,
        }
    ]


async def test_the_guardian_agenda_shows_the_holidays_but_no_lessons(api: Api) -> None:
    body = (await api.get(f"{GUARDIAN}?from=2025-12-08&to=2025-12-14")).json()
    assert kinds_of(body) == {"holiday": 1}


async def test_each_account_has_the_interviews_of_its_own_guardian(api: Api) -> None:
    marta = (await api.get(f"{GUARDIAN}?from=2025-10-20&to=2025-11-16&kind=interview")).json()
    pablo_path = "/v1/accounts/pablo/guardian/agenda?from=2025-10-20&to=2025-11-16&kind=interview"
    pablo = (await api.get(pablo_path)).json()
    assert [item["title"] for item in marta["items"]] == ["Entrevista: Aceptada"]
    assert [item["title"] for item in pablo["items"]] == ["Entrevista: Pendiente"]


async def test_the_guardian_agenda_is_stored_apart_from_the_children(api: Api) -> None:
    await api.get(LUCIA)
    first = await api.get(GUARDIAN)
    second = await api.get(GUARDIAN)
    assert (first.headers["x-cache"], second.headers["x-cache"]) == ("miss", "hit")


async def test_a_login_without_a_guardian_has_no_guardian_agenda(api: Api) -> None:
    api.harness.sim.options.home_without_guardian = True
    body = problem_of(await api.get(GUARDIAN), status=404, code="guardian_not_found")
    assert "children's agendas are still available" in body["detail"]
    assert (await api.get(LUCIA)).status_code == 200


async def test_a_guardian_the_portal_begins_to_list_is_found_after_a_fresh_read(api: Api) -> None:
    api.harness.sim.options.home_without_guardian = True
    problem_of(await api.get(GUARDIAN), status=404, code="guardian_not_found")
    api.harness.sim.options.home_without_guardian = False

    before = api.portal_calls()
    problem_of(await api.get(GUARDIAN), status=404, code="guardian_not_found")
    assert api.portal_calls() == before
    assert (await api.get(f"{GUARDIAN}?fresh=true")).status_code == 200


async def test_a_feed_the_portal_fails_to_build_is_a_bad_gateway_that_names_the_feed(
    api: Api,
) -> None:
    api.harness.sim.options.agenda_feed_fails = True
    body = problem_of(await api.get(LUCIA), status=502, code="unexpected_reply")
    assert "agenda-feed" in body["detail"]


async def test_a_feed_that_changed_shape_is_a_bad_gateway_that_says_the_portal_changed(
    api: Api,
) -> None:
    api.harness.sim.options.agenda_bad_event = True
    problem_of(await api.get(LUCIA), status=502, code="portal_changed")


async def test_a_failed_read_is_not_stored(api: Api) -> None:
    api.harness.sim.options.agenda_feed_fails = True
    problem_of(await api.get(LUCIA), status=502, code="unexpected_reply")
    api.harness.sim.options.agenda_feed_fails = False
    again = await api.get(LUCIA)
    assert (again.status_code, again.headers["x-cache"]) == (200, "miss")


@pytest.mark.parametrize("path", [LUCIA, GUARDIAN])
async def test_every_agenda_route_says_503_for_a_blocked_account(
    make_api: MakeApi, harness: Harness, path: str
) -> None:
    api = await make_api(accounts={"marta": harness.account_settings(password="not-the-password")})
    await api.post(f"{ACCOUNT}/connection/check")
    problem_of(await api.get(path), status=503, code="breaker_open")
    assert api.harness.sim.counters.login_attempts == 1


days = st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31))


@given(
    today=days,
    offset=st.integers(min_value=-1100, max_value=1100),
    length=st.integers(min_value=1, max_value=366),
)
def test_a_range_that_is_short_and_near_today_is_always_accepted(
    today: date, offset: int, length: int
) -> None:
    first = today + timedelta(days=offset)
    last = first + timedelta(days=length - 1)
    window = resolve_window(today, first, last)
    assert (window.first, window.last) == (first, last)


@given(today=days, offset=st.integers(min_value=-1100, max_value=1100))
def test_a_range_without_an_end_is_always_a_week_that_is_accepted(today: date, offset: int) -> None:
    first = today + timedelta(days=offset)
    window = resolve_window(today, first, None)
    assert (window.first, window.last) == (first, first + timedelta(days=6))


@given(today=days, first=st.none() | days, last=st.none() | days)
def test_a_range_is_refused_with_a_reason_or_it_meets_every_rule(
    today: date, first: date | None, last: date | None
) -> None:
    refusal: ApiError | None = None
    try:
        window = resolve_window(today, first, last)
    except ApiError as error:
        refusal = error
    if refusal is not None:
        assert (refusal.status, refusal.code) == (422, "invalid_window")
        return
    assert window.first <= window.last
    assert (window.last - window.first).days + 1 <= 366
    assert abs((window.first - today).days) <= 1100
    assert first is None or window.first == first
    assert last is None or window.last == last


@given(
    today=days,
    offset=st.one_of(
        st.integers(min_value=1101, max_value=20000), st.integers(min_value=-20000, max_value=-1101)
    ),
    length=st.integers(min_value=1, max_value=366),
)
def test_a_range_far_from_today_is_always_refused(today: date, offset: int, length: int) -> None:
    first = today + timedelta(days=offset)
    with pytest.raises(ApiError) as refusal:
        resolve_window(today, first, first + timedelta(days=length - 1))
    assert refusal.value.code == "invalid_window"


@given(today=days, first=days, extra=st.integers(min_value=366, max_value=5000))
def test_a_range_over_a_year_is_always_refused(today: date, first: date, extra: int) -> None:
    with pytest.raises(ApiError) as refusal:
        resolve_window(today, first, first + timedelta(days=extra))
    assert refusal.value.code == "invalid_window"


def test_every_kind_of_entry_can_be_asked_for() -> None:
    assert EVENT_KINDS == ("lesson", "interview", "holiday", "school_event")
