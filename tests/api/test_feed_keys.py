import logging

import pytest

from tests.api.support import CALENDAR_MEDIA_TYPE, Api, MakeApi, bearer, problem_of

ACCOUNT = "/v1/accounts/marta"
FEED_ROUTES = [
    f"{ACCOUNT}/children/lucia/agenda.ics",
    f"{ACCOUNT}/guardian/agenda.ics",
    f"{ACCOUNT}/agenda.ics",
]
JSON_ROUTES = [
    "/v1/accounts",
    f"{ACCOUNT}/children",
    f"{ACCOUNT}/children/lucia/agenda",
    f"{ACCOUNT}/guardian/agenda",
]


def new_feed_key(api: Api, *accounts: str) -> str:
    return api.keys.create("calendar", scopes=["feed"], accounts=list(accounts) or ["*"]).key


@pytest.mark.parametrize("path", FEED_ROUTES)
async def test_a_key_that_holds_only_the_feed_scope_opens_every_calendar_from_the_url(
    api: Api, path: str
) -> None:
    key = new_feed_key(api)
    response = await api.client.get(path, params={"key": key})
    assert response.status_code == 200
    assert response.headers["content-type"] == CALENDAR_MEDIA_TYPE
    assert response.content.startswith(b"BEGIN:VCALENDAR")


@pytest.mark.parametrize("path", FEED_ROUTES)
@pytest.mark.parametrize("how", ["bearer", "header"])
async def test_a_feed_key_also_works_in_a_header(api: Api, path: str, how: str) -> None:
    key = new_feed_key(api)
    headers = bearer(key) if how == "bearer" else {"X-API-Key": key}
    assert (await api.client.get(path, headers=headers)).status_code == 200


@pytest.mark.parametrize("path", FEED_ROUTES)
@pytest.mark.parametrize("scopes", [["read"], ["write"], ["admin"], ["feed", "read"]], ids="+".join)
async def test_a_key_that_holds_more_than_the_feed_scope_is_refused_in_a_url(
    api: Api, path: str, scopes: list[str]
) -> None:
    key = api.keys.create("wide", scopes=scopes, accounts=["*"]).key
    response = await api.client.get(path, params={"key": key})
    body = problem_of(response, status=403, code="key_not_allowed_in_url")
    assert "--scope feed" in body["detail"]
    assert key not in response.text
    assert api.portal_calls() == 0


@pytest.mark.parametrize("path", FEED_ROUTES)
@pytest.mark.parametrize("which", ["read", "admin"])
async def test_a_key_that_holds_more_than_the_feed_scope_still_works_in_a_header(
    api: Api, path: str, which: str
) -> None:
    key = api.read_key if which == "read" else api.admin_key
    assert (await api.get(path, key=key)).status_code == 200


@pytest.mark.parametrize("path", FEED_ROUTES)
async def test_a_wrong_key_in_a_url_is_refused_with_a_challenge(api: Api, path: str) -> None:
    response = await api.client.get(path, params={"key": "afk_not-a-real-key"})
    problem_of(response, status=401, code="invalid_api_key")
    assert response.headers["www-authenticate"].startswith("Bearer")


@pytest.mark.parametrize("path", FEED_ROUTES)
async def test_a_feed_without_a_key_says_how_a_calendar_app_can_send_one(
    api: Api, path: str
) -> None:
    response = await api.client.get(path)
    body = problem_of(response, status=401, code="missing_api_key")
    assert "?key=" in body["detail"]
    assert "feed scope" in body["detail"]
    assert response.headers["www-authenticate"].startswith("Bearer")


async def test_a_route_that_is_not_a_feed_does_not_suggest_a_key_in_the_url(api: Api) -> None:
    body = problem_of(await api.client.get("/v1/accounts"), status=401, code="missing_api_key")
    assert "?key=" not in body["detail"]


@pytest.mark.parametrize("path", FEED_ROUTES)
async def test_an_empty_key_in_the_url_counts_as_no_key(api: Api, path: str) -> None:
    response = await api.client.get(path, params={"key": ""})
    problem_of(response, status=401, code="missing_api_key")


@pytest.mark.parametrize("route", JSON_ROUTES)
@pytest.mark.parametrize("which", ["feed", "read", "admin"])
async def test_a_route_that_is_not_a_feed_never_takes_a_key_from_the_url(
    api: Api, route: str, which: str
) -> None:
    keys = {"feed": new_feed_key(api), "read": api.read_key, "admin": api.admin_key}
    response = await api.client.get(route, params={"key": keys[which]})
    body = problem_of(response, status=401, code="missing_api_key")
    assert "?key=" not in body["detail"]
    assert api.portal_calls() == 0


@pytest.mark.parametrize("path", FEED_ROUTES)
async def test_a_key_in_a_header_counts_before_a_key_in_the_url(api: Api, path: str) -> None:
    feed = new_feed_key(api)
    good_header = await api.client.get(
        path, headers=bearer(api.read_key), params={"key": "afk_wrong"}
    )
    bad_header = await api.client.get(path, headers=bearer("afk_wrong"), params={"key": feed})
    assert good_header.status_code == 200
    problem_of(bad_header, status=401, code="invalid_api_key")


async def test_a_wide_key_in_a_header_is_not_refused_because_of_a_url_key_next_to_it(
    api: Api,
) -> None:
    feed = new_feed_key(api)
    response = await api.client.get(
        FEED_ROUTES[0], headers=bearer(api.admin_key), params={"key": feed}
    )
    assert response.status_code == 200


@pytest.mark.parametrize("path", FEED_ROUTES)
async def test_a_feed_key_made_for_one_account_opens_no_other(api: Api, path: str) -> None:
    key = new_feed_key(api, "pablo")
    response = await api.client.get(path, params={"key": key})
    problem_of(response, status=404, code="account_not_found")
    assert api.portal_calls() == 0
    own = await api.client.get("/v1/accounts/pablo/agenda.ics", params={"key": key})
    assert own.status_code == 200


async def test_an_unknown_account_has_no_calendar_for_a_feed_key(api: Api) -> None:
    key = new_feed_key(api)
    response = await api.client.get("/v1/accounts/nobody/agenda.ics", params={"key": key})
    problem_of(response, status=404, code="account_not_found")


async def test_a_feed_key_cannot_read_the_data_behind_the_calendar(api: Api) -> None:
    key = new_feed_key(api)
    for route in (f"{ACCOUNT}/children/lucia/agenda", f"{ACCOUNT}/guardian/agenda"):
        response = await api.client.get(route, headers=bearer(key))
        body = problem_of(response, status=403, code="insufficient_scope")
        assert body["needed"] == "read"
    assert api.portal_calls() == 0


async def test_a_revoked_feed_key_stops_working_at_once(api: Api) -> None:
    key = new_feed_key(api)
    assert (await api.client.get(FEED_ROUTES[2], params={"key": key})).status_code == 200
    assert api.keys.revoke("calendar")
    response = await api.client.get(FEED_ROUTES[2], params={"key": key})
    problem_of(response, status=401, code="invalid_api_key")


async def test_a_feed_key_used_in_a_url_counts_against_its_limit(make_api: MakeApi) -> None:
    api = await make_api(rate_limit_per_minute=2)
    key = new_feed_key(api)
    for _ in range(2):
        assert (await api.client.get(FEED_ROUTES[2], params={"key": key})).status_code == 200
    response = await api.client.get(FEED_ROUTES[2], params={"key": key})
    problem_of(response, status=429, code="rate_limited")
    assert int(response.headers["retry-after"]) >= 1


async def test_a_key_the_url_refused_still_counts_against_its_limit(make_api: MakeApi) -> None:
    api = await make_api(rate_limit_per_minute=2)
    for _ in range(2):
        response = await api.client.get(FEED_ROUTES[2], params={"key": api.read_key})
        problem_of(response, status=403, code="key_not_allowed_in_url")
    response = await api.client.get(FEED_ROUTES[2], params={"key": api.read_key})
    problem_of(response, status=429, code="rate_limited")


async def test_a_key_in_a_url_never_reaches_a_server_log(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    feed = new_feed_key(api)
    secrets = (feed, api.read_key, "afk_not-a-real-key")
    with caplog.at_level(logging.DEBUG):
        for secret in secrets:
            await api.client.get(FEED_ROUTES[2], params={"key": secret, "back": 3})
    server = [
        record for record in caplog.records if not record.name.startswith(("httpx", "httpcore"))
    ]
    written = " ".join(f"{record.getMessage()} {record.__dict__}" for record in server)
    assert "/v1/accounts/{account}/agenda.ics" in written
    for secret in secrets:
        assert secret not in written


async def test_the_access_line_of_a_calendar_names_the_key_and_never_its_secret(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    feed = new_feed_key(api)
    with caplog.at_level(logging.INFO, logger="alexia_api.access"):
        await api.client.get(FEED_ROUTES[2], params={"key": feed})
    [record] = [record for record in caplog.records if record.name == "alexia_api.access"]
    assert record.__dict__["key"] == "calendar"
    assert feed not in f"{record.getMessage()} {record.__dict__}"


async def test_a_problem_never_repeats_the_key_it_answers(api: Api) -> None:
    feed = new_feed_key(api)
    cases: list[tuple[str, dict[str, str], int]] = [
        (api.read_key, {}, 403),
        ("afk_not-a-real-key", {}, 401),
        (feed, {"back": "x"}, 422),
    ]
    for key, extra, status in cases:
        response = await api.client.get(FEED_ROUTES[0], params={"key": key, **extra})
        assert response.status_code == status
        assert key not in response.text
        assert key not in " ".join(response.headers.values())


async def test_a_calendar_never_repeats_the_key_that_asked_for_it(api: Api) -> None:
    key = new_feed_key(api)
    response = await api.client.get(FEED_ROUTES[2], params={"key": key})
    assert key.encode() not in response.content
    assert key not in " ".join(response.headers.values())
