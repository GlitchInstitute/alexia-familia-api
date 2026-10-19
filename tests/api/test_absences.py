"""The absences of a child."""

import asyncio

from alexia_api.sim.absences import SimAbsence
from alexia_api.sim.world import DEMO_USER_A, synthetic_guid
from tests.api.support import Api, MakeApi, problem_of

CHILDREN = "/v1/accounts/marta/children"
MATEO = f"{CHILDREN}/mateo/absences"
LUCIA = f"{CHILDREN}/lucia/absences"
LUCIA_STUDENT = synthetic_guid(0x101)
A_NEW_ABSENCE = SimAbsence(
    synthetic_guid(0x7599), "2026-10-01", "Falta de asistencia", teacher="Ana Muestra"
)
MATEOS_ABSENCES = [synthetic_guid(0x7501 + index) for index in range(4)]


async def test_the_absences_of_a_child_come_newest_first_with_every_field(api: Api) -> None:
    response = await api.get(MATEO)

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == MATEOS_ABSENCES
    assert items[0] == {
        "id": synthetic_guid(0x7501),
        "occurred_on": "2026-10-14",
        "hour": None,
        "area": "Tutoría",
        "teacher": "Rosa Prueba",
        "incident": "Falta de asistencia",
        "note": None,
        "justifiable": True,
        "justified": False,
        "justification": None,
        "accepted": False,
    }
    assert items[3] == {
        "id": synthetic_guid(0x7504),
        "occurred_on": "2026-10-09",
        "hour": "09:05",
        "area": "Música",
        "teacher": "Tomás Demo",
        "incident": "Retraso",
        "note": "Llegó con el autobús siguiente.",
        "justifiable": False,
        "justified": False,
        "justification": None,
        "accepted": False,
    }


async def test_a_justified_absence_says_whether_the_school_accepted_it(api: Api) -> None:
    items = (await api.get(MATEO)).json()["items"]

    justified = [(item["justified"], item["justification"], item["accepted"]) for item in items]
    assert justified[1:3] == [(True, "Enfermedad", True), (True, "Cita médica", False)]


async def test_a_child_without_incidents_has_an_empty_list(api: Api) -> None:
    response = await api.get(LUCIA)

    assert (response.status_code, response.json()) == (200, {"items": []})


async def test_each_account_lists_only_the_absences_of_its_own_children(api: Api) -> None:
    alba = await api.get("/v1/accounts/pablo/children/alba/absences")

    assert [item["id"] for item in alba.json()["items"]] == [
        synthetic_guid(0x7511),
        synthetic_guid(0x7512),
    ]
    problem_of(await api.get(f"{CHILDREN}/alba/absences"), status=404, code="child_not_found")


async def test_the_second_read_comes_from_the_cache_and_costs_no_portal_call(api: Api) -> None:
    first = await api.get(MATEO)
    api.harness.clock.advance(30)
    second = await api.get(MATEO)

    assert (first.headers["x-cache"], first.headers["age"]) == ("miss", "0")
    assert (second.headers["x-cache"], second.headers["age"]) == ("hit", "30")
    assert second.json() == first.json()
    assert api.harness.requests_to("Justificar.aspx") == 2


async def test_fresh_asks_the_portal_again(api: Api) -> None:
    await api.get(MATEO)
    again = await api.get(f"{MATEO}?fresh=true")

    assert again.headers["x-cache"] == "bypass"
    assert api.harness.requests_to("Justificar.aspx") == 4


async def test_absences_are_stored_for_each_child_on_their_own(api: Api) -> None:
    await api.get(MATEO)
    await api.get(LUCIA)
    third = await api.get(MATEO)

    assert third.headers["x-cache"] == "hit"
    assert api.harness.requests_to("Justificar.aspx") == 4


async def test_stored_absences_expire_after_ten_minutes(api: Api) -> None:
    await api.get(MATEO)
    api.harness.clock.advance(599)
    assert (await api.get(MATEO)).headers["x-cache"] == "hit"

    api.harness.clock.advance(2)

    assert (await api.get(MATEO)).headers["x-cache"] == "miss"


async def test_the_time_to_store_absences_is_a_setting(make_api: MakeApi) -> None:
    api = await make_api(cache={"absences": 0})

    await api.get(MATEO)

    assert (await api.get(MATEO)).headers["x-cache"] == "miss"


async def test_children_read_at_the_same_moment_never_get_each_others_rows(api: Api) -> None:
    api.harness.revise_child(DEMO_USER_A, LUCIA_STUDENT, absences=(A_NEW_ABSENCE,))
    paths = (LUCIA, MATEO) * 4

    answers = await asyncio.gather(*(api.get(f"{path}?fresh=true") for path in paths))

    for path, answer in zip(paths, answers, strict=True):
        ids = [item["id"] for item in answer.json()["items"]]
        assert ids == ([A_NEW_ABSENCE.id] if path == LUCIA else MATEOS_ABSENCES), path


async def test_a_missing_child_costs_no_portal_call_once_the_list_is_known(api: Api) -> None:
    await api.get(CHILDREN)
    before = api.portal_calls()

    problem_of(await api.get(f"{CHILDREN}/ghost/absences"), status=404, code="child_not_found")

    assert api.portal_calls() == before


async def test_a_grid_the_portal_changed_is_a_bad_gateway_that_names_the_row(api: Api) -> None:
    api.harness.sim.options.grid_cell_count = 13

    body = problem_of(await api.get(MATEO), status=502, code="portal_changed")

    assert "absence row 0: 13 cells instead of 14" in body["detail"]


async def test_a_failed_read_is_not_stored(api: Api) -> None:
    api.harness.sim.options.grid_not_json = True
    problem_of(await api.get(MATEO), status=502, code="portal_changed")
    api.harness.sim.options.grid_not_json = False

    again = await api.get(MATEO)

    assert (again.status_code, again.headers["x-cache"]) == (200, "miss")


async def test_a_session_the_portal_dropped_is_replaced_without_the_client_noticing(
    api: Api,
) -> None:
    await api.get(MATEO)
    api.harness.sim.expire_all_sessions()

    response = await api.get(f"{MATEO}?fresh=true")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 4
    assert api.harness.sim.counters.login_attempts == 2
