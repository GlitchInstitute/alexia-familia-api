import pytest

from alexia_api.domain.errors import PortalError, Transport
from alexia_api.services.registry import AccountRuntime
from alexia_api.sim.world import DEMO_PASSWORD_B, DEMO_USER_B
from tests.api.support import Api, MakeApi, problem_of
from tests.harness import Harness


async def with_wrong_password(make_api: MakeApi, harness: Harness) -> Api:
    """An application whose first account has a wrong password and whose second is fine."""
    return await make_api(
        accounts={
            "marta": harness.account_settings(password="not-the-password"),
            "pablo": harness.account_settings(DEMO_USER_B, DEMO_PASSWORD_B),
        }
    )


async def test_the_list_shows_every_account_without_calling_the_portal(api: Api) -> None:
    response = await api.get("/v1/accounts")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == ["marta", "pablo"]
    assert items[0] == {
        "id": "marta",
        "label": "marta",
        "portal_host": "sim.invalid",
        "connection": {"state": "logged_out"},
        "capabilities": {"writes": False, "forms": False, "restore_unread": False},
        "child_count": None,
    }
    assert api.portal_calls() == 0


async def test_the_list_says_which_switches_the_operator_turned_on(make_api: MakeApi) -> None:
    api = await make_api(allow_writes=True, allow_forms=True, restore_unread=True)
    item = (await api.get("/v1/accounts/marta")).json()
    assert item["capabilities"] == {"writes": True, "forms": True, "restore_unread": True}


async def test_one_account_can_be_shown_by_name(api: Api) -> None:
    response = await api.get("/v1/accounts/pablo")
    assert response.status_code == 200
    assert response.json()["id"] == "pablo"


async def test_an_unknown_account_is_not_found(api: Api) -> None:
    problem_of(await api.get("/v1/accounts/nobody"), status=404, code="account_not_found")


async def test_checking_an_account_logs_in_and_the_next_check_reuses_the_session(
    api: Api,
) -> None:
    first = await api.post("/v1/accounts/marta/connection/check")
    second = await api.post("/v1/accounts/marta/connection/check")
    assert first.status_code == 200
    assert first.json() == {"session": "new", "child_count": 2}
    assert second.json() == {"session": "reused", "child_count": 2}
    assert api.harness.sim.counters.login_attempts == 1


async def test_a_logged_in_account_shows_when_in_the_offset_of_the_school(api: Api) -> None:
    await api.post("/v1/accounts/marta/connection/check")
    item = (await api.get("/v1/accounts/marta")).json()
    assert item["child_count"] == 2
    assert item["connection"]["state"] == "logged_in"
    assert item["connection"]["since"].endswith("+01:00")
    assert item["connection"]["last_success_at"].endswith("+01:00")


async def test_accounts_are_independent_of_each_other(api: Api) -> None:
    await api.post("/v1/accounts/pablo/connection/check")
    states = {
        item["id"]: item["connection"]["state"]
        for item in (await api.get("/v1/accounts")).json()["items"]
    }
    assert states == {"marta": "logged_out", "pablo": "logged_in"}


async def test_a_wrong_password_is_tried_once_and_then_the_account_is_blocked(
    make_api: MakeApi, harness: Harness
) -> None:
    api = await with_wrong_password(make_api, harness)
    first = await api.post("/v1/accounts/marta/connection/check")
    second = await api.post("/v1/accounts/marta/connection/check")
    third = await api.get("/v1/accounts/marta/children")
    problem_of(first, status=503, code="invalid_credentials")
    blocked = problem_of(second, status=503, code="breaker_open")
    problem_of(third, status=503, code="breaker_open")
    assert blocked["cause"] == "invalid_credentials"
    assert blocked["since"].endswith("+01:00")
    assert api.harness.sim.counters.login_attempts == 1


async def test_a_blocked_account_shows_its_cause_and_leaves_the_others_working(
    make_api: MakeApi, harness: Harness
) -> None:
    api = await with_wrong_password(make_api, harness)
    await api.post("/v1/accounts/marta/connection/check")
    items = {item["id"]: item for item in (await api.get("/v1/accounts")).json()["items"]}
    assert items["marta"]["connection"]["state"] == "blocked"
    assert items["marta"]["connection"]["cause"] == "invalid_credentials"
    assert (await api.get("/v1/accounts/pablo/children")).status_code == 200
    assert (await api.get("/v1/accounts/pablo")).json()["connection"]["state"] == "logged_in"


async def test_an_admin_lifts_a_block_and_the_next_call_tries_the_login_again(
    make_api: MakeApi, harness: Harness
) -> None:
    api = await with_wrong_password(make_api, harness)
    await api.post("/v1/accounts/marta/connection/check")
    lifted = await api.post("/v1/accounts/marta/connection/reset", key=api.admin_key)
    again = await api.post("/v1/accounts/marta/connection/reset", key=api.admin_key)
    assert lifted.json() == {"was_blocked": True}
    assert again.json() == {"was_blocked": False}
    problem_of(
        await api.post("/v1/accounts/marta/connection/check"),
        status=503,
        code="invalid_credentials",
    )
    assert api.harness.sim.counters.login_attempts == 2


async def test_a_portal_in_maintenance_does_not_block_the_account(api: Api) -> None:
    api.harness.sim.options.maintenance = "http503"
    problem_of(
        await api.post("/v1/accounts/marta/connection/check"),
        status=503,
        code="portal_maintenance",
    )
    assert (await api.get("/v1/accounts/marta")).json()["connection"]["state"] == "logged_out"
    api.harness.sim.options.maintenance = "none"
    assert (await api.post("/v1/accounts/marta/connection/check")).status_code == 200


async def test_a_portal_that_does_not_answer_in_time_is_a_gateway_timeout(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def times_out(*_arguments: object, **_keywords: object) -> None:
        raise PortalError(Transport("timeout"))

    monkeypatch.setattr(AccountRuntime, "check", times_out)
    problem_of(await api.post("/v1/accounts/marta/connection/check"), status=504, code="transport")


async def test_the_check_answers_with_nothing_but_the_session_and_the_count(api: Api) -> None:
    body = (await api.post("/v1/accounts/marta/connection/check")).json()
    assert set(body) == {"session", "child_count"}


async def test_the_check_and_the_reset_only_answer_to_post(api: Api) -> None:
    for action in ("check", "reset"):
        response = await api.get(f"/v1/accounts/marta/connection/{action}")
        problem_of(response, status=405, code="method_not_allowed")
