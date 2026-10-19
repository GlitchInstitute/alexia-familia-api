import asyncio

import pytest

from alexia_api.sim.world import DEMO_PASSWORD_B, DEMO_USER_A, DEMO_USER_B, synthetic_guid
from tests.api.support import Api, MakeApi, problem_of
from tests.harness import A_NEW_SIBLING, Harness

LUCIA = synthetic_guid(0x101)
MATEO = synthetic_guid(0x102)
HUGO = synthetic_guid(0x111)
CHILDREN = "/v1/accounts/marta/children"


async def test_the_list_has_each_child_of_the_account_with_a_slug(api: Api) -> None:
    response = await api.get(CHILDREN)
    assert response.status_code == 200
    items = response.json()["items"]
    assert [(item["id"], item["slug"]) for item in items] == [(LUCIA, "lucia"), (MATEO, "mateo")]
    assert items[0] == {
        "id": LUCIA,
        "person_id": synthetic_guid(0x201),
        "slug": "lucia",
        "name": "Lucía Ejemplo Muestra",
        "first_name": "Lucía",
        "relation": "Hija",
    }


async def test_each_account_lists_only_its_own_children(api: Api) -> None:
    marta = (await api.get(CHILDREN)).json()["items"]
    pablo = (await api.get("/v1/accounts/pablo/children")).json()["items"]
    assert [item["slug"] for item in marta] == ["lucia", "mateo"]
    assert [item["slug"] for item in pablo] == ["hugo", "alba"]


async def test_the_second_read_comes_from_the_cache_and_says_how_old_it_is(api: Api) -> None:
    first = await api.get(CHILDREN)
    api.harness.clock.advance(30)
    second = await api.get(CHILDREN)
    assert first.headers["x-cache"] == "miss"
    assert first.headers["age"] == "0"
    assert second.headers["x-cache"] == "hit"
    assert second.headers["age"] == "30"
    assert second.json() == first.json()
    assert api.harness.requests_to("HomeMetro.aspx") == 2


async def test_fresh_asks_the_portal_again(api: Api) -> None:
    await api.get(CHILDREN)
    again = await api.get(f"{CHILDREN}?fresh=true")
    assert again.headers["x-cache"] == "bypass"
    assert again.headers["age"] == "0"
    assert api.harness.requests_to("HomeMetro.aspx") == 3


async def test_a_stored_list_expires_after_its_time(api: Api) -> None:
    await api.get(CHILDREN)
    api.harness.clock.advance(901)
    assert (await api.get(CHILDREN)).headers["x-cache"] == "miss"


@pytest.mark.parametrize(
    "reference", [LUCIA, LUCIA.upper(), "lucia", "LUCIA", "Lucia"], ids=str.lower
)
async def test_a_child_is_found_by_id_or_slug_in_any_case(api: Api, reference: str) -> None:
    response = await api.get(f"{CHILDREN}/{reference}")
    assert response.status_code == 200
    assert response.json()["id"] == LUCIA


async def test_a_child_of_another_account_is_not_found(api: Api) -> None:
    for reference in (HUGO, "hugo"):
        problem_of(await api.get(f"{CHILDREN}/{reference}"), status=404, code="child_not_found")
    assert (await api.get("/v1/accounts/pablo/children/hugo")).status_code == 200


async def test_a_missing_child_costs_no_portal_call_once_the_list_is_known(api: Api) -> None:
    await api.get(CHILDREN)
    before = api.portal_calls()
    problem_of(await api.get(f"{CHILDREN}/ghost"), status=404, code="child_not_found")
    assert api.portal_calls() == before


async def test_a_missing_child_says_how_to_find_a_new_sibling(api: Api) -> None:
    body = problem_of(await api.get(f"{CHILDREN}/ghost"), status=404, code="child_not_found")
    assert "fresh=true" in body["detail"]


async def test_a_new_sibling_appears_after_the_list_is_read_fresh(api: Api) -> None:
    await api.get(CHILDREN)
    api.harness.enrol(DEMO_USER_A, A_NEW_SIBLING)

    problem_of(await api.get(f"{CHILDREN}/ines"), status=404, code="child_not_found")
    await api.get(f"{CHILDREN}?fresh=true")
    assert (await api.get(f"{CHILDREN}/ines")).status_code == 200


async def test_the_tracking_counters_of_each_child(api: Api) -> None:
    lucia = await api.get(f"{CHILDREN}/lucia/tracking")
    mateo = await api.get(f"{CHILDREN}/mateo/tracking")
    assert lucia.json() == {"tasks": 3, "activities": 1, "notes": 0, "tests": 2, "incidents": 0}
    assert mateo.json() == {"tasks": 1, "activities": 0, "notes": 2, "tests": 0, "incidents": 1}


async def test_tracking_is_stored_for_each_child_on_its_own(api: Api) -> None:
    await api.get(f"{CHILDREN}/lucia/tracking")
    await api.get(f"{CHILDREN}/mateo/tracking")
    third = await api.get(f"{CHILDREN}/lucia/tracking")
    assert third.headers["x-cache"] == "hit"
    assert api.harness.requests_to("GetWPSeguimiento") == 2


async def test_tracking_fresh_asks_the_portal_again(api: Api) -> None:
    await api.get(f"{CHILDREN}/lucia/tracking")
    again = await api.get(f"{CHILDREN}/lucia/tracking?fresh=true")
    assert again.headers["x-cache"] == "bypass"
    assert api.harness.requests_to("GetWPSeguimiento") == 2


async def test_tracking_is_stored_for_less_time_than_the_list(api: Api) -> None:
    await api.get(f"{CHILDREN}/lucia/tracking")
    api.harness.clock.advance(121)
    assert (await api.get(f"{CHILDREN}/lucia/tracking")).headers["x-cache"] == "miss"
    assert (await api.get(CHILDREN)).headers["x-cache"] == "hit"


async def test_the_staff_a_guardian_can_meet(api: Api) -> None:
    response = await api.get(f"{CHILDREN}/lucia/staff")
    assert response.status_code == 200
    assert response.json()["items"] == [
        {"id": synthetic_guid(0x601), "name": "Ana Muestra Tutora", "role": "Tutora"},
        {"id": synthetic_guid(0x602), "name": "Carlos Ejemplo Profesor", "role": "Matemáticas"},
    ]


async def test_siblings_have_their_own_staff(api: Api) -> None:
    lucia = (await api.get(f"{CHILDREN}/lucia/staff")).json()["items"]
    mateo = (await api.get(f"{CHILDREN}/mateo/staff")).json()["items"]
    assert {item["name"] for item in lucia} != {item["name"] for item in mateo}


async def test_a_pinned_slug_is_the_name_in_urls(make_api: MakeApi, harness: Harness) -> None:
    api = await make_api(
        accounts={
            "marta": harness.account_settings(slugs={"first-born": LUCIA}),
            "pablo": harness.account_settings(DEMO_USER_B, DEMO_PASSWORD_B),
        }
    )
    items = (await api.get(CHILDREN)).json()["items"]
    assert [item["slug"] for item in items] == ["first-born", "mateo"]
    assert (await api.get(f"{CHILDREN}/first-born/tracking")).status_code == 200
    problem_of(await api.get(f"{CHILDREN}/lucia"), status=404, code="child_not_found")


async def test_many_requests_at_once_share_one_portal_read(api: Api) -> None:
    await api.post("/v1/accounts/marta/connection/check")
    before = api.harness.requests_to("HomeMetro.aspx")
    responses = await asyncio.gather(*(api.get(CHILDREN) for _ in range(8)))
    assert {response.status_code for response in responses} == {200}
    assert api.harness.requests_to("HomeMetro.aspx") == before + 1


async def test_a_session_the_portal_dropped_is_replaced_without_the_client_noticing(
    api: Api,
) -> None:
    await api.get(CHILDREN)
    api.harness.sim.expire_all_sessions()
    response = await api.get(f"{CHILDREN}?fresh=true")
    assert response.status_code == 200
    assert api.harness.sim.counters.login_attempts == 2


@pytest.mark.parametrize(
    "path",
    [
        CHILDREN,
        f"{CHILDREN}/lucia",
        f"{CHILDREN}/lucia/tracking",
        f"{CHILDREN}/lucia/staff",
        f"{CHILDREN}/mateo/absences",
    ],
)
async def test_every_child_route_says_503_for_a_blocked_account(
    make_api: MakeApi, harness: Harness, path: str
) -> None:
    api = await make_api(accounts={"marta": harness.account_settings(password="not-the-password")})
    await api.post("/v1/accounts/marta/connection/check")
    problem_of(await api.get(path), status=503, code="breaker_open")
    assert api.harness.sim.counters.login_attempts == 1
