import logging
import re

import pytest

from alexia_api.services.registry import AccountRuntime
from tests.api.support import Api, MakeApi

GENERATED_ID = re.compile(r"[0-9a-f]{32}")
POLICY = "default-src 'none'; frame-ancestors 'none'"


STANDARD_RECORD_FIELDS = set(
    logging.LogRecord("x", logging.INFO, "x", 1, "x", (), None).__dict__
) | {"message", "asctime"}


def access_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == "alexia_api.access"]


def what_the_server_logged(record: logging.LogRecord) -> str:
    """The text and the extra fields the server put in a record.

    The standard fields are left out because `logging` fills them in from the source file, and
    a checkout can live in a directory with any name, such as `private` or `fresh-clone`.
    """
    extras = {k: v for k, v in record.__dict__.items() if k not in STANDARD_RECORD_FIELDS}
    return f"{record.msg} {record.args!r} {record.getMessage()} {extras!r}"


async def test_a_request_id_is_made_when_none_is_sent(api: Api) -> None:
    first = await api.client.get("/healthz")
    second = await api.client.get("/healthz")
    assert GENERATED_ID.fullmatch(first.headers["x-request-id"])
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


async def test_a_plain_request_id_from_a_proxy_is_kept(api: Api) -> None:
    sent = "proxy-id_1234.abc~9"
    response = await api.client.get("/healthz", headers={"X-Request-Id": sent})
    assert response.headers["x-request-id"] == sent


@pytest.mark.parametrize(
    "sent", ["short", "x" * 65, "has space inside", "inject%0d%0aheader", "semi;colon;1234"]
)
async def test_a_request_id_that_is_not_plain_is_replaced_and_never_echoed(
    api: Api, sent: str
) -> None:
    response = await api.client.get("/healthz", headers={"X-Request-Id": sent})
    assert GENERATED_ID.fullmatch(response.headers["x-request-id"])


async def test_a_problem_carries_the_id_the_proxy_sent(api: Api) -> None:
    sent = "proxy-id-for-a-failure"
    response = await api.client.get("/v1/accounts", headers={"X-Request-Id": sent})
    assert response.status_code == 401
    assert response.json()["request_id"] == sent
    assert response.headers["x-request-id"] == sent


async def test_every_answer_carries_the_protective_headers(api: Api) -> None:
    for response in (
        await api.client.get("/healthz"),
        await api.get("/v1/accounts"),
        await api.client.get("/v1/accounts"),
        await api.client.get("/nowhere"),
    ):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["content-security-policy"] == POLICY


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
async def test_documentation_pages_load_scripts_so_they_get_no_policy(api: Api, path: str) -> None:
    response = await api.client.get(path)
    assert response.status_code == 200
    assert "content-security-policy" not in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_the_openapi_document_is_data_so_it_gets_the_policy(api: Api) -> None:
    response = await api.client.get("/openapi.json")
    assert response.headers["content-security-policy"] == POLICY


async def test_the_access_line_names_the_route_and_not_the_path(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="alexia_api.access"):
        response = await api.get(
            "/v1/accounts/marta/children/lucia/tracking?fresh=true&token=abc123"
        )
    [record] = access_records(caplog)
    pattern = r"GET /v1/accounts/\{account\}/children/\{child\}/tracking 200 \d+ms"
    assert re.fullmatch(pattern, record.getMessage())
    assert record.__dict__["request_id"] == response.headers["x-request-id"]
    assert record.__dict__["account"] == "marta"
    assert record.__dict__["key"] == "reader"
    everything = what_the_server_logged(record)
    for private in ("lucia", "token", "abc123", "fresh", api.read_key):
        assert private not in everything


async def test_an_unmatched_address_is_logged_without_its_text(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="alexia_api.access"):
        await api.client.get("/some/private/address")
    [record] = access_records(caplog)
    assert re.fullmatch(r"GET unmatched 404 \d+ms", record.getMessage())
    assert "private" not in what_the_server_logged(record)


@pytest.mark.parametrize("key", [None, "afk_wrong"])
async def test_a_refused_key_is_logged_without_a_key_name(
    api: Api, caplog: pytest.LogCaptureFixture, key: str | None
) -> None:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    with caplog.at_level(logging.INFO, logger="alexia_api.access"):
        await api.client.get("/v1/accounts", headers=headers)
    [record] = access_records(caplog)
    assert " 401 " in record.getMessage()
    assert record.__dict__["key"] is None
    assert "afk_wrong" not in what_the_server_logged(record)


async def test_a_rate_limited_request_is_logged_with_the_name_of_its_key(
    make_api: MakeApi, caplog: pytest.LogCaptureFixture
) -> None:
    api = await make_api(rate_limit_per_minute=1)
    await api.get("/v1/accounts")
    with caplog.at_level(logging.INFO, logger="alexia_api.access"):
        await api.get("/v1/accounts")
    [record] = access_records(caplog)
    assert " 429 " in record.getMessage()
    assert record.__dict__["key"] == "reader"


async def test_a_server_error_is_logged_with_its_status(
    api: Api, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def broken(*_arguments: object, **_keywords: object) -> None:
        raise RuntimeError("inside")

    monkeypatch.setattr(AccountRuntime, "directory", broken)
    with caplog.at_level(logging.INFO, logger="alexia_api.access"):
        await api.get("/v1/accounts/marta/children")
    [record] = access_records(caplog)
    assert " 500 " in record.getMessage()
