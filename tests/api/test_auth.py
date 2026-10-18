import pytest

from alexia_api.services.keys import FILE_NAME
from tests.api.support import Api, MakeApi, bearer, problem_of

CHILD_ROUTES = (
    "/v1/accounts/marta/children",
    "/v1/accounts/marta/children/lucia",
    "/v1/accounts/marta/children/lucia/tracking",
    "/v1/accounts/marta/children/lucia/staff",
)


async def test_a_call_without_a_key_is_refused_with_a_challenge(api: Api) -> None:
    response = await api.client.get("/v1/accounts")
    problem_of(response, status=401, code="missing_api_key")
    assert response.headers["www-authenticate"].startswith("Bearer")


async def test_a_wrong_key_is_refused_with_a_challenge(api: Api) -> None:
    response = await api.get("/v1/accounts", key="afk_not-a-real-key")
    problem_of(response, status=401, code="invalid_api_key")
    assert response.headers["www-authenticate"].startswith("Bearer")


async def test_the_key_works_as_a_bearer_token(api: Api) -> None:
    response = await api.client.get("/v1/accounts", headers=bearer(api.read_key))
    assert response.status_code == 200


async def test_the_key_works_in_the_x_api_key_header(api: Api) -> None:
    response = await api.client.get("/v1/accounts", headers={"X-API-Key": api.read_key})
    assert response.status_code == 200


async def test_the_bearer_token_is_the_one_that_counts_when_both_are_sent(api: Api) -> None:
    good_bearer = await api.client.get(
        "/v1/accounts", headers={**bearer(api.read_key), "X-API-Key": "afk_wrong"}
    )
    bad_bearer = await api.client.get(
        "/v1/accounts", headers={**bearer("afk_wrong"), "X-API-Key": api.read_key}
    )
    assert good_bearer.status_code == 200
    problem_of(bad_bearer, status=401, code="invalid_api_key")


async def test_another_authorization_scheme_does_not_count_as_a_key(api: Api) -> None:
    response = await api.client.get(
        "/v1/accounts", headers={"Authorization": f"Basic {api.read_key}"}
    )
    problem_of(response, status=401, code="missing_api_key")


async def test_another_scheme_leaves_room_for_the_header_key(api: Api) -> None:
    response = await api.client.get(
        "/v1/accounts",
        headers={"Authorization": "Basic dXNlcjpwYXNz", "X-API-Key": api.read_key},
    )
    assert response.status_code == 200


@pytest.mark.parametrize("headers", [{"Authorization": "Bearer "}, {"X-API-Key": ""}])
async def test_an_empty_key_counts_as_no_key(api: Api, headers: dict[str, str]) -> None:
    response = await api.client.get("/v1/accounts", headers=headers)
    problem_of(response, status=401, code="missing_api_key")


async def test_a_new_key_works_at_once_and_a_revoked_one_stops_at_once(api: Api) -> None:
    issued = api.keys.create("temporary", scopes=["read"], accounts=["*"])
    assert (await api.get("/v1/accounts", key=issued.key)).status_code == 200
    assert api.keys.revoke("temporary")
    problem_of(await api.get("/v1/accounts", key=issued.key), status=401, code="invalid_api_key")


async def test_a_key_file_that_cannot_be_read_refuses_every_key(api: Api) -> None:
    (api.harness.state_dir / FILE_NAME).write_text("this is not json", encoding="utf-8")
    for key in (api.read_key, api.admin_key):
        problem_of(await api.get("/v1/accounts", key=key), status=401, code="invalid_api_key")


async def test_a_key_that_holds_only_the_feed_scope_cannot_read(api: Api) -> None:
    issued = api.keys.create("calendar", scopes=["feed"], accounts=["*"])
    response = await api.get("/v1/accounts", key=issued.key)
    body = problem_of(response, status=403, code="insufficient_scope")
    assert body["needed"] == "read"


async def test_the_read_scope_cannot_do_what_needs_admin(api: Api) -> None:
    response = await api.post("/v1/accounts/marta/connection/reset")
    body = problem_of(response, status=403, code="insufficient_scope")
    assert body["needed"] == "admin"
    assert api.portal_calls() == 0


async def test_the_admin_scope_includes_the_read_scope(api: Api) -> None:
    response = await api.get("/v1/accounts", key=api.admin_key)
    assert response.status_code == 200


async def test_a_key_sees_only_the_accounts_it_was_made_for(api: Api) -> None:
    issued = api.keys.create("pablo-only", scopes=["read"], accounts=["pablo"])
    response = await api.get("/v1/accounts", key=issued.key)
    assert [item["id"] for item in response.json()["items"]] == ["pablo"]


async def test_an_account_a_key_may_not_use_looks_like_one_that_does_not_exist(api: Api) -> None:
    issued = api.keys.create("pablo-only", scopes=["read"], accounts=["pablo"])
    hidden = await api.get("/v1/accounts/marta", key=issued.key)
    missing = await api.get("/v1/accounts/nobody", key=issued.key)
    hidden_body = problem_of(hidden, status=404, code="account_not_found")
    missing_body = problem_of(missing, status=404, code="account_not_found")
    assert hidden_body["detail"].replace("marta", "nobody") == missing_body["detail"]
    assert api.portal_calls() == 0


@pytest.mark.parametrize("path", CHILD_ROUTES)
async def test_a_hidden_account_has_no_child_routes_either(api: Api, path: str) -> None:
    issued = api.keys.create("pablo-only", scopes=["read"], accounts=["pablo"])
    response = await api.get(path, key=issued.key)
    problem_of(response, status=404, code="account_not_found")
    assert api.portal_calls() == 0


async def test_a_hidden_account_cannot_be_checked_or_reset(api: Api) -> None:
    issued = api.keys.create("pablo-admin", scopes=["admin"], accounts=["pablo"])
    for action in ("check", "reset"):
        response = await api.post(f"/v1/accounts/marta/connection/{action}", key=issued.key)
        problem_of(response, status=404, code="account_not_found")
    assert api.portal_calls() == 0


async def test_a_key_that_asks_too_often_is_told_when_to_come_back(make_api: MakeApi) -> None:
    api = await make_api(rate_limit_per_minute=3)
    for _ in range(3):
        assert (await api.get("/v1/accounts")).status_code == 200
    response = await api.get("/v1/accounts")
    body = problem_of(response, status=429, code="rate_limited")
    assert body["retry_after_seconds"] == int(response.headers["retry-after"]) == 20
    api.harness.clock.advance(20)
    assert (await api.get("/v1/accounts")).status_code == 200


async def test_each_key_has_its_own_limit(make_api: MakeApi) -> None:
    api = await make_api(rate_limit_per_minute=2)
    for _ in range(2):
        await api.get("/v1/accounts")
    assert (await api.get("/v1/accounts")).status_code == 429
    assert (await api.get("/v1/accounts", key=api.admin_key)).status_code == 200


async def test_wrong_keys_do_not_use_up_the_limit_of_a_right_one(make_api: MakeApi) -> None:
    api = await make_api(rate_limit_per_minute=2)
    for _ in range(10):
        await api.get("/v1/accounts", key="afk_wrong")
    assert (await api.get("/v1/accounts")).status_code == 200
    assert (await api.get("/v1/accounts")).status_code == 200


async def test_a_limit_of_zero_turns_the_limit_off(make_api: MakeApi) -> None:
    api = await make_api(rate_limit_per_minute=0)
    for _ in range(40):
        assert (await api.get("/v1/accounts")).status_code == 200
