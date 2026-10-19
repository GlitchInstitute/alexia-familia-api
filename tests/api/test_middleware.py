import logging
import re

import pytest

from alexia_api.api.middleware import host_is_listed, host_name_of
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


@pytest.mark.parametrize(
    ("typed", "marker"),
    [
        ("zoe", "zoe"),
        ("x%0A2026-10-19T03:13:40Z%20INFO%20alexia_api.server%20forged", "forged"),
        ("a" * 500, "a" * 50),
    ],
)
async def test_an_account_name_that_nobody_configured_is_never_logged(
    api: Api, caplog: pytest.LogCaptureFixture, typed: str, marker: str
) -> None:
    with caplog.at_level(logging.INFO, logger="alexia_api.access"):
        response = await api.get(f"/v1/accounts/{typed}")
    [record] = access_records(caplog)
    assert response.status_code == 404
    assert record.__dict__["account"] is None
    assert marker not in what_the_server_logged(record)


async def test_a_caller_without_a_valid_key_cannot_put_an_account_name_in_the_log(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="alexia_api.access"):
        await api.client.get("/v1/accounts/marta/children")
    [record] = access_records(caplog)
    assert " 401 " in record.getMessage()
    assert record.__dict__["account"] is None


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("/v1/accounts/zoe", "account_not_found"),
        ("/nowhere", "not_found"),
        ("/v1/accounts/marta/children/lucia/tracking?fresh=maybe", "validation_error"),
    ],
)
async def test_a_failed_request_is_logged_with_the_code_of_its_problem(
    api: Api, caplog: pytest.LogCaptureFixture, path: str, code: str
) -> None:
    with caplog.at_level(logging.INFO, logger="alexia_api.access"):
        response = await api.get(path)
    [record] = access_records(caplog)
    assert response.json()["code"] == code
    assert record.__dict__["code"] == code


async def test_a_request_that_worked_is_logged_without_a_code(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="alexia_api.access"):
        await api.get("/v1/accounts")
    [record] = access_records(caplog)
    assert " 200 " in record.getMessage()
    assert record.__dict__["code"] is None


@pytest.mark.parametrize(
    ("headers", "code"),
    [({}, "missing_api_key"), ({"Authorization": "Bearer afk_wrong"}, "invalid_api_key")],
)
async def test_a_refused_key_is_logged_with_the_code_that_says_why(
    api: Api, caplog: pytest.LogCaptureFixture, headers: dict[str, str], code: str
) -> None:
    with caplog.at_level(logging.INFO, logger="alexia_api.access"):
        await api.client.get("/v1/accounts", headers=headers)
    [record] = access_records(caplog)
    assert record.__dict__["code"] == code


async def test_a_refused_host_is_logged_with_its_code_and_not_its_name(
    make_api: MakeApi, caplog: pytest.LogCaptureFixture
) -> None:
    api = await make_api(allowed_hosts=["api.test"])
    with caplog.at_level(logging.INFO, logger="alexia_api.access"):
        await api.client.get("/", headers={"Host": "elsewhere.test"})
    [record] = access_records(caplog)
    assert record.__dict__["code"] == "invalid_host"
    assert "elsewhere" not in what_the_server_logged(record)


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
    assert record.__dict__["code"] == "rate_limited"


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
    assert record.__dict__["code"] == "internal_error"


@pytest.mark.parametrize(
    ("header", "name"),
    [
        ("api.test", "api.test"),
        ("API.Test:8000", "api.test"),
        ("  api.test  ", "api.test"),
        ("my-api.under_score.test", "my-api.under_score.test"),
        ("10.1.2.3:80", "10.1.2.3"),
        ("[::1]:8000", "[::1]"),
        ("[FE80::1]", "[fe80::1]"),
        ("", None),
        ("api.test:", None),
        ("api.test:123456", None),
        ("api.test@evil.test", None),
        ("api.test:80@evil.test", None),
        ("api.test/path", None),
        ("api test", None),
        ("[::1", None),
    ],
)
def test_a_host_header_gives_a_plain_name_or_nothing(header: str, name: str | None) -> None:
    assert host_name_of(header) == name


@pytest.mark.parametrize(
    ("header", "listed", "expected"),
    [
        ("api.test", ["api.test"], True),
        ("api.test", ["other.test", "api.test"], True),
        ("api.test", ["API.Test"], True),
        ("my-api.test", ["my-api.test"], True),
        ("under_score.test", ["under_score.test"], True),
        ("other.test", ["api.test"], False),
        ("x@a.api.test", ["*.api.test"], False),
        ("api.test", [], False),
        ("a.api.test", ["*.api.test"], True),
        ("a.b.api.test", ["*.api.test"], True),
        ("api.test", ["*.api.test"], False),
        (".api.test", ["*.api.test"], False),
        ("evilapi.test", ["*.api.test"], False),
        ("[::1]:8000", ["[::1]"], True),
        ("[::2]", ["[::1]"], False),
        ("api.test@evil.test", ["api.test"], False),
    ],
)
def test_a_host_is_listed_by_its_name_or_by_a_subdomain_entry(
    header: str, listed: list[str], expected: bool
) -> None:
    assert host_is_listed(header, listed) is expected
