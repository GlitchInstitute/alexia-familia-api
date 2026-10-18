import asyncio
import logging
from pathlib import Path

import httpx
import pytest
from starlette.types import ASGIApp, Message, Scope

from alexia_api import __version__
from alexia_api.api.app import create_app
from alexia_api.config import ConfigError
from alexia_api.services.keys import FILE_NAME, ApiKeyStore
from tests.api.support import Api, MakeApi, bearer

ORIGIN = "https://app.example.test"


async def run_lifespan(app: ASGIApp) -> None:
    """Start the application and stop it again, the way a server does."""
    received: asyncio.Queue[Message] = asyncio.Queue()
    sent: asyncio.Queue[Message] = asyncio.Queue()
    scope: Scope = {"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}

    async def serve() -> None:
        await app(scope, received.get, sent.put)

    task = asyncio.create_task(serve())
    await received.put({"type": "lifespan.startup"})
    assert (await sent.get())["type"] == "lifespan.startup.complete"
    await received.put({"type": "lifespan.shutdown"})
    assert (await sent.get())["type"] == "lifespan.shutdown.complete"
    await task


def client_for(app: ASGIApp) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://api.test",
    )


async def test_a_bare_environment_starts_a_server_that_says_it_is_not_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ALEXIA_API_STATE_DIR", str(tmp_path / "state"))
    async with client_for(create_app()) as client:
        assert (await client.get("/healthz")).status_code == 200
        readiness = await client.get("/readyz")
    assert readiness.status_code == 503
    assert readiness.json()["checks"] == {"accounts": "failed", "keys": "failed", "state_dir": "ok"}


async def test_the_server_reads_its_file_and_its_secrets_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = tmp_path / "state"
    config = tmp_path / "alexia-api.toml"
    config.write_text(
        f"""
state_dir = "{state}"

[accounts.marta]
label = "Marta"
portal_url = "https://portal.example.test"
institution_key = "demo-school"
username = "env:MARTA_USER"
password = "env:MARTA_PASSWORD"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ALEXIA_API_CONFIG", str(config))
    monkeypatch.setenv("MARTA_USER", "marta.ejemplo")
    monkeypatch.setenv("MARTA_PASSWORD", "demo-password-a")
    key = ApiKeyStore(state / FILE_NAME).create("reader", scopes=["read"], accounts=["*"]).key
    async with client_for(create_app()) as client:
        response = await client.get("/v1/accounts", headers=bearer(key))
        readiness = await client.get("/readyz")
    [account] = response.json()["items"]
    assert (account["id"], account["label"]) == ("marta", "Marta")
    assert account["portal_host"] == "portal.example.test"
    assert readiness.status_code == 200


async def test_a_secret_that_is_missing_stops_the_server_before_it_starts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "alexia-api.toml"
    config.write_text(
        f"""
state_dir = "{tmp_path / "state"}"

[accounts.marta]
portal_url = "https://portal.example.test"
institution_key = "demo-school"
username = "env:MARTA_USER"
password = "env:MARTA_PASSWORD"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ALEXIA_API_CONFIG", str(config))
    monkeypatch.delenv("MARTA_USER", raising=False)
    monkeypatch.delenv("MARTA_PASSWORD", raising=False)
    with pytest.raises(ConfigError, match="MARTA_USER"):
        create_app()


async def test_the_gateways_are_closed_when_the_server_stops(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[bool] = []

    async def spy() -> None:
        closed.append(True)

    monkeypatch.setattr(api.app.state.services.registry, "aclose", spy)
    await run_lifespan(api.app)
    assert closed == [True]


async def test_the_gateways_are_closed_even_when_the_server_stops_after_an_error(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[bool] = []

    async def spy() -> None:
        closed.append(True)

    monkeypatch.setattr(api.app.state.services.registry, "aclose", spy)
    with pytest.raises(RuntimeError, match="stop"):
        async with api.app.router.lifespan_context(api.app):
            raise RuntimeError("stop")
    assert closed == [True]


async def test_cors_is_off_unless_origins_are_listed(api: Api) -> None:
    response = await api.get("/v1/accounts", headers={"Origin": ORIGIN})
    assert "access-control-allow-origin" not in response.headers


async def test_a_listed_origin_may_call_from_a_browser(make_api: MakeApi) -> None:
    api = await make_api(cors_origins=[ORIGIN])
    preflight = await api.client.options(
        "/v1/accounts",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    answer = await api.get("/v1/accounts", headers={"Origin": ORIGIN})
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == ORIGIN
    assert "authorization" in preflight.headers["access-control-allow-headers"].lower()
    assert answer.headers["access-control-allow-origin"] == ORIGIN
    assert "x-request-id" in answer.headers["access-control-expose-headers"].lower()
    assert "access-control-allow-credentials" not in answer.headers


async def test_an_origin_that_is_not_listed_gets_no_permission(make_api: MakeApi) -> None:
    api = await make_api(cors_origins=[ORIGIN])
    other = "https://elsewhere.example.test"
    preflight = await api.client.options(
        "/v1/accounts", headers={"Origin": other, "Access-Control-Request-Method": "GET"}
    )
    answer = await api.get("/v1/accounts", headers={"Origin": other})
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    assert "access-control-allow-origin" not in answer.headers


async def test_a_browser_may_not_use_a_method_the_api_does_not_have(make_api: MakeApi) -> None:
    api = await make_api(cors_origins=[ORIGIN])
    preflight = await api.client.options(
        "/v1/accounts", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "PUT"}
    )
    assert preflight.status_code == 400


async def test_only_listed_hosts_are_served(make_api: MakeApi) -> None:
    api = await make_api(allowed_hosts=["api.test"])
    assert (await api.client.get("/healthz")).status_code == 200
    refused = await api.client.get("/healthz", headers={"Host": "elsewhere.test"})
    assert refused.status_code == 400
    assert "x-request-id" in refused.headers


async def test_any_host_is_served_when_none_are_listed(api: Api) -> None:
    response = await api.client.get("/healthz", headers={"Host": "anything.test"})
    assert response.status_code == 200


def started_line(caplog: pytest.LogCaptureFixture) -> str:
    [line] = [r.getMessage() for r in caplog.records if r.name == "alexia_api.server"]
    return line


async def test_the_server_says_who_it_serves_when_it_starts(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="alexia_api"):
        await run_lifespan(api.app)

    assert started_line(caplog) == (
        f"alexia-familia-api {__version__} is up, accounts marta, pablo, "
        "writes off, documentation on"
    )


async def test_the_start_line_shows_when_writes_are_on_and_documentation_is_off(
    make_api: MakeApi, caplog: pytest.LogCaptureFixture
) -> None:
    api = await make_api(allow_writes=True, docs_enabled=False)

    with caplog.at_level(logging.INFO, logger="alexia_api"):
        await run_lifespan(api.app)

    assert started_line(caplog).endswith("writes on, documentation off")


async def test_the_start_line_says_so_when_there_are_no_accounts(
    make_api: MakeApi, caplog: pytest.LogCaptureFixture
) -> None:
    api = await make_api(accounts={})

    with caplog.at_level(logging.INFO, logger="alexia_api"):
        await run_lifespan(api.app)

    assert "accounts none," in started_line(caplog)


async def test_the_start_line_holds_no_portal_address_and_no_secret(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="alexia_api"):
        await run_lifespan(api.app)

    text = " ".join(record.getMessage() for record in caplog.records)
    assert "sim.invalid" not in text
    assert "demo-password" not in text
