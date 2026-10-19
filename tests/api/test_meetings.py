"""The meetings of a child, and the days and hours that the staff has free for new ones."""

import asyncio
from datetime import date, timedelta

import pytest

from alexia_api.sim.meetings import SimMeeting
from alexia_api.sim.world import DEMO_USER_A, synthetic_guid
from tests.api.support import Api, MakeApi, problem_of
from tests.harness import teacher

CHILDREN = "/v1/accounts/marta/children"
LUCIA = f"{CHILDREN}/lucia/meetings"
MATEO = f"{CHILDREN}/mateo/meetings"
LUCIA_STUDENT = synthetic_guid(0x101)
MATEO_STUDENT = synthetic_guid(0x102)
MUSIC = synthetic_guid(0x604)
TUTOR_B = synthetic_guid(0x603)
DAYS = f"{CHILDREN}/mateo/staff/{MUSIC}/availability"
HOURS = f"{DAYS}/2026-01-06"
TODAY = date(2026, 1, 1)
A_NEW_MEETING = SimMeeting(
    synthetic_guid(0x7499), "Pendiente", (2, 3), "Ana Muestra Tutora", "Marta Ejemplo"
)
LUCIAS_MEETINGS = [synthetic_guid(number) for number in (0x7302, 0x7301, 0x7303)]
MUSIC_IN_JANUARY = [
    "2026-01-06",
    "2026-01-08",
    "2026-01-13",
    "2026-01-15",
    "2026-01-20",
    "2026-01-22",
    "2026-01-27",
    "2026-01-29",
]


def ids_of(body: dict[str, list[dict[str, str]]]) -> list[str]:
    return [item["id"] for item in body["items"]]


async def test_the_meetings_of_a_child_come_in_the_order_they_take_place(api: Api) -> None:
    response = await api.get(LUCIA)

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == LUCIAS_MEETINGS
    assert items[0]["state"] == "done"
    assert items[1] == {
        "id": synthetic_guid(0x7301),
        "state": "accepted",
        "state_label": "Aceptada",
        "starts_at": "2025-10-20T16:00:00+02:00",
        "requested_by": "Marta Ejemplo",
        "staff": "Ana Muestra Tutora",
        "note": None,
    }
    assert items[2] == {
        "id": synthetic_guid(0x7303),
        "state": "cancelled",
        "state_label": "Cancelada",
        "starts_at": "2026-01-15T15:30:00+01:00",
        "requested_by": "Marta Ejemplo",
        "staff": "Carlos Ejemplo Profesor",
        "note": "La familia no puede asistir.",
    }


async def test_a_child_without_meetings_has_an_empty_list(api: Api) -> None:
    response = await api.get(MATEO)

    assert (response.status_code, response.json()) == (200, {"items": []})


async def test_a_group_meeting_starts_at_midnight_and_says_the_time_in_its_note(api: Api) -> None:
    response = await api.get("/v1/accounts/pablo/children/alba/meetings")

    (item,) = response.json()["items"]
    assert item["starts_at"] == "2025-09-18T00:00:00+02:00"
    assert "17:30" in item["note"]


async def test_a_word_the_server_does_not_know_is_unknown_and_keeps_its_label(api: Api) -> None:
    review = SimMeeting(synthetic_guid(0x7498), "En revisión", (3, 4), "Ana", "Marta Ejemplo")
    api.harness.revise_child(DEMO_USER_A, MATEO_STUDENT, meetings=(review,))

    (item,) = (await api.get(MATEO)).json()["items"]

    assert (item["state"], item["state_label"]) == ("unknown", "En revisión")


async def test_each_account_lists_only_the_meetings_of_its_own_children(api: Api) -> None:
    hugo = await api.get("/v1/accounts/pablo/children/hugo/meetings")

    assert ids_of(hugo.json()) == [synthetic_guid(0x7311)]
    problem_of(await api.get(f"{CHILDREN}/hugo/meetings"), status=404, code="child_not_found")


async def test_the_second_read_comes_from_the_cache_and_costs_no_portal_call(api: Api) -> None:
    first = await api.get(LUCIA)
    api.harness.clock.advance(30)
    second = await api.get(LUCIA)

    assert (first.headers["x-cache"], first.headers["age"]) == ("miss", "0")
    assert (second.headers["x-cache"], second.headers["age"]) == ("hit", "30")
    assert second.json() == first.json()
    assert api.harness.requests_to("Entrevistas.aspx") == 2


async def test_fresh_asks_the_portal_again(api: Api) -> None:
    await api.get(LUCIA)
    again = await api.get(f"{LUCIA}?fresh=true")

    assert again.headers["x-cache"] == "bypass"
    assert api.harness.requests_to("Entrevistas.aspx") == 4


async def test_meetings_are_stored_for_each_child_on_their_own(api: Api) -> None:
    await api.get(LUCIA)
    await api.get(MATEO)
    third = await api.get(LUCIA)

    assert third.headers["x-cache"] == "hit"
    assert api.harness.requests_to("Entrevistas.aspx") == 4


async def test_stored_meetings_expire_after_five_minutes(api: Api) -> None:
    await api.get(LUCIA)
    api.harness.clock.advance(299)
    assert (await api.get(LUCIA)).headers["x-cache"] == "hit"

    api.harness.clock.advance(2)

    assert (await api.get(LUCIA)).headers["x-cache"] == "miss"


async def test_the_time_to_store_meetings_is_a_setting(make_api: MakeApi) -> None:
    api = await make_api(cache={"meetings": 0})

    await api.get(LUCIA)

    assert (await api.get(LUCIA)).headers["x-cache"] == "miss"


async def test_a_change_at_the_school_shows_with_fresh(api: Api) -> None:
    await api.get(LUCIA)
    api.harness.revise_child(DEMO_USER_A, LUCIA_STUDENT, meetings=(A_NEW_MEETING,))

    stored = await api.get(LUCIA)
    fresh = await api.get(f"{LUCIA}?fresh=true")

    assert ids_of(stored.json()) == LUCIAS_MEETINGS
    assert ids_of(fresh.json()) == [A_NEW_MEETING.id]


async def test_children_read_at_the_same_moment_never_get_each_others_meetings(api: Api) -> None:
    other = SimMeeting(synthetic_guid(0x7497), "Aceptada", (3, 5), "Rosa", "Marta Ejemplo")
    api.harness.revise_child(DEMO_USER_A, LUCIA_STUDENT, meetings=(A_NEW_MEETING,))
    api.harness.revise_child(DEMO_USER_A, MATEO_STUDENT, meetings=(other,))
    paths = (LUCIA, MATEO) * 4

    answers = await asyncio.gather(*(api.get(f"{path}?fresh=true") for path in paths))

    for path, answer in zip(paths, answers, strict=True):
        assert ids_of(answer.json()) == [(A_NEW_MEETING if path == LUCIA else other).id], path


async def test_a_missing_child_costs_no_portal_call_once_the_list_is_known(api: Api) -> None:
    await api.get(CHILDREN)
    before = api.portal_calls()

    problem_of(await api.get(f"{CHILDREN}/ghost/meetings"), status=404, code="child_not_found")

    assert api.portal_calls() == before


async def test_a_grid_the_portal_changed_is_a_bad_gateway_that_names_the_row(api: Api) -> None:
    api.harness.sim.options.grid_cell_count = 13

    body = problem_of(await api.get(LUCIA), status=502, code="portal_changed")

    assert "meeting row 0: 13 cells instead of 12" in body["detail"]


async def test_a_failed_read_of_the_meetings_is_not_stored(api: Api) -> None:
    api.harness.sim.options.grid_not_json = True
    problem_of(await api.get(LUCIA), status=502, code="portal_changed")
    api.harness.sim.options.grid_not_json = False

    again = await api.get(LUCIA)

    assert (again.status_code, again.headers["x-cache"]) == (200, "miss")


async def test_a_session_the_portal_dropped_is_replaced_for_the_meetings(api: Api) -> None:
    await api.get(LUCIA)
    api.harness.sim.expire_all_sessions()

    response = await api.get(f"{LUCIA}?fresh=true")

    assert response.status_code == 200
    assert ids_of(response.json()) == LUCIAS_MEETINGS
    assert api.harness.sim.counters.login_attempts == 2


async def test_the_days_of_a_month_with_a_free_hour_come_earliest_first(api: Api) -> None:
    response = await api.get(DAYS)

    assert response.status_code == 200
    assert response.json() == {"month": "2026-01", "items": MUSIC_IN_JANUARY}


async def test_a_day_with_two_free_hours_is_listed_once(api: Api) -> None:
    items = (await api.get(DAYS)).json()["items"]

    assert items.count("2026-01-06") == 1


async def test_a_month_can_be_asked_for_by_name(api: Api) -> None:
    response = await api.get(f"{DAYS}?month=2026-02")

    assert response.json() == {
        "month": "2026-02",
        "items": [
            "2026-02-03",
            "2026-02-05",
            "2026-02-10",
            "2026-02-12",
            "2026-02-17",
            "2026-02-19",
            "2026-02-24",
            "2026-02-26",
        ],
    }


async def test_each_person_has_the_days_that_they_offer(api: Api) -> None:
    response = await api.get(f"{CHILDREN}/mateo/staff/{TUTOR_B}/availability")

    assert response.json()["items"] == ["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26"]


async def test_a_month_that_is_over_has_no_free_days(api: Api) -> None:
    response = await api.get(f"{DAYS}?month=2025-12")

    assert response.json() == {"month": "2025-12", "items": []}


async def test_the_month_that_is_asked_for_by_default_is_the_month_at_the_school(
    api: Api,
) -> None:
    api.harness.clock.advance(30 * 86400 + 23 * 3600 + 30 * 60)

    response = await api.get(DAYS)

    assert response.json()["month"] == "2026-02"


async def test_the_free_slots_of_a_day_carry_the_offset_of_the_school(api: Api) -> None:
    response = await api.get(HOURS)

    assert response.status_code == 200
    assert response.json() == {
        "day": "2026-01-06",
        "items": [
            {"starts_at": "2026-01-06T15:30:00+01:00", "ends_at": "2026-01-06T16:00:00+01:00"},
            {"starts_at": "2026-01-06T16:00:00+01:00", "ends_at": "2026-01-06T16:30:00+01:00"},
        ],
    }


async def test_the_offset_of_a_slot_follows_the_clock_change_of_the_school(api: Api) -> None:
    response = await api.get(f"{DAYS}/2026-07-14")

    (first, _) = response.json()["items"]
    assert first["starts_at"] == "2026-07-14T15:30:00+02:00"


async def test_a_day_without_free_hours_has_an_empty_list(api: Api) -> None:
    response = await api.get(f"{DAYS}/2026-01-07")

    assert response.json() == {"day": "2026-01-07", "items": []}


async def test_a_person_who_is_not_on_the_staff_list_of_the_child_is_not_found(api: Api) -> None:
    lucia_staff = f"{CHILDREN}/lucia/staff/{MUSIC}/availability"

    body = problem_of(await api.get(lucia_staff), status=404, code="staff_not_found")
    problem_of(await api.get(f"{lucia_staff}/2026-01-06"), status=404, code="staff_not_found")

    assert MUSIC in body["detail"]


@pytest.mark.parametrize("staff", [synthetic_guid(0x999), "not-a-guid", "%20", "x" * 200])
async def test_a_person_that_nobody_lists_is_not_found(api: Api, staff: str) -> None:
    path = f"{CHILDREN}/mateo/staff/{staff}/availability"

    problem_of(await api.get(path), status=404, code="staff_not_found")
    problem_of(await api.get(f"{path}/2026-01-06"), status=404, code="staff_not_found")


async def test_an_unknown_person_costs_no_portal_call_once_the_staff_list_is_known(
    api: Api,
) -> None:
    await api.get(DAYS)
    before = api.portal_calls()

    problem_of(
        await api.get(f"{CHILDREN}/mateo/staff/{synthetic_guid(0x999)}/availability"),
        status=404,
        code="staff_not_found",
    )

    assert api.portal_calls() == before


async def test_the_id_of_a_person_may_be_written_in_capital_letters(api: Api) -> None:
    response = await api.get(f"{CHILDREN}/mateo/staff/{MUSIC.upper()}/availability")

    assert response.json()["items"] == MUSIC_IN_JANUARY


async def test_two_children_who_share_a_teacher_share_the_stored_answer(api: Api) -> None:
    api.harness.revise_child(DEMO_USER_A, LUCIA_STUDENT, staff=(teacher(0x604),))

    first = await api.get(DAYS)
    second = await api.get(f"{CHILDREN}/lucia/staff/{MUSIC}/availability")

    assert (first.headers["x-cache"], second.headers["x-cache"]) == ("miss", "hit")
    assert second.json() == first.json()
    assert api.harness.requests_to("GetFechasDisponibles") == 1


async def test_each_account_keeps_its_own_free_hours(api: Api) -> None:
    mine = await api.get(DAYS)
    theirs = await api.get(f"/v1/accounts/pablo/children/hugo/staff/{MUSIC}/availability")

    assert (mine.headers["x-cache"], theirs.headers["x-cache"]) == ("miss", "miss")
    assert api.harness.requests_to("GetFechasDisponibles") == 2


async def test_the_free_days_are_stored_for_a_minute(api: Api) -> None:
    first = await api.get(DAYS)
    api.harness.clock.advance(59)
    second = await api.get(DAYS)
    api.harness.clock.advance(2)
    third = await api.get(DAYS)

    assert [r.headers["x-cache"] for r in (first, second, third)] == ["miss", "hit", "miss"]
    assert second.headers["age"] == "59"


async def test_the_free_days_and_the_free_hours_are_stored_apart(api: Api) -> None:
    await api.get(DAYS)
    hours = await api.get(HOURS)
    again = await api.get(DAYS)

    assert (hours.headers["x-cache"], again.headers["x-cache"]) == ("miss", "hit")


async def test_each_month_and_each_day_is_stored_on_its_own(api: Api) -> None:
    await api.get(DAYS)
    await api.get(HOURS)

    next_month = await api.get(f"{DAYS}?month=2026-02")
    next_day = await api.get(f"{DAYS}/2026-01-08")

    assert (next_month.headers["x-cache"], next_day.headers["x-cache"]) == ("miss", "miss")


async def test_fresh_reads_the_free_hours_again_and_keeps_the_staff_list(api: Api) -> None:
    await api.get(DAYS)
    again = await api.get(f"{DAYS}?fresh=true")

    assert again.headers["x-cache"] == "bypass"
    assert api.harness.requests_to("GetFechasDisponibles") == 2
    assert api.harness.requests_to("GetEmpleadosByHijo") == 1


async def test_the_time_to_store_free_hours_is_a_setting(make_api: MakeApi) -> None:
    api = await make_api(cache={"availability": 0})

    await api.get(HOURS)

    assert (await api.get(HOURS)).headers["x-cache"] == "miss"


async def test_a_text_the_portal_writes_another_way_is_a_bad_gateway(api: Api) -> None:
    api.harness.sim.options.availability_bad_entry = True

    days = problem_of(await api.get(DAYS), status=502, code="portal_changed")
    hours = problem_of(await api.get(HOURS), status=502, code="portal_changed")

    assert days["detail"] == "the portal changed the shape of availability days"
    assert hours["detail"] == "the portal changed the shape of availability hours"


async def test_a_failed_read_of_free_hours_is_not_stored(api: Api) -> None:
    api.harness.sim.options.availability_bad_entry = True
    problem_of(await api.get(DAYS), status=502, code="portal_changed")
    api.harness.sim.options.availability_bad_entry = False

    again = await api.get(DAYS)

    assert (again.status_code, again.headers["x-cache"]) == (200, "miss")


@pytest.mark.parametrize(
    "month", ["2026-13", "2026-00", "2026-1", "26-01", "0000-01", "2026-01-06", "january", ""]
)
async def test_a_month_that_is_not_written_year_dash_month_is_refused(api: Api, month: str) -> None:
    body = problem_of(await api.get(f"{DAYS}?month={month}"), status=422, code="validation_error")

    assert body["errors"][0]["location"] == ["query", "month"]
    assert api.harness.requests_to("GetFechasDisponibles") == 0


@pytest.mark.parametrize("day", ["2026-02-30", "2026-13-01", "tomorrow", "06-01-2026", "2026-1-6"])
async def test_a_day_that_is_not_a_date_is_refused(api: Api, day: str) -> None:
    body = problem_of(await api.get(f"{DAYS}/{day}"), status=422, code="validation_error")

    assert body["errors"][0]["location"] == ["path", "day"]
    assert api.harness.requests_to("GetHorasByFecha") == 0


@pytest.mark.parametrize(("month", "allowed"), [("2029-01", True), ("2029-02", False)])
async def test_a_month_may_start_up_to_1100_days_from_today(
    api: Api, month: str, allowed: bool
) -> None:
    response = await api.get(f"{DAYS}?month={month}")

    if allowed:
        assert response.status_code == 200
    else:
        body = problem_of(response, status=422, code="invalid_window")
        assert body["detail"] == "month must be within 1100 days of today, which is 2026-01-01"
        assert api.harness.requests_to("GetFechasDisponibles") == 0


@pytest.mark.parametrize(
    ("distance", "allowed"), [(1100, True), (1101, False), (-1100, True), (-1101, False)]
)
async def test_a_day_may_lie_up_to_1100_days_from_today(
    api: Api, distance: int, allowed: bool
) -> None:
    day = (TODAY + timedelta(days=distance)).isoformat()

    response = await api.get(f"{DAYS}/{day}")

    if allowed:
        assert response.status_code == 200
    else:
        body = problem_of(response, status=422, code="invalid_window")
        assert body["detail"] == "day must be within 1100 days of today, which is 2026-01-01"
        assert api.harness.requests_to("GetHorasByFecha") == 0
