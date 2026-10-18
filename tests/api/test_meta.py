import shutil

from alexia_api import __version__
from alexia_api.services.keys import FILE_NAME
from tests.api.support import Api, MakeApi

READY = {"accounts": "ok", "keys": "ok", "state_dir": "ok"}


async def test_the_index_names_the_server_and_points_at_the_documentation(api: Api) -> None:
    response = await api.client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "name": "alexia-familia-api",
        "version": __version__,
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "/healthz",
    }


async def test_the_index_points_nowhere_when_the_documentation_is_off(make_api: MakeApi) -> None:
    api = await make_api(docs_enabled=False)
    body = (await api.client.get("/")).json()
    assert body["docs"] is None
    assert body["openapi"] is None


async def test_health_answers_without_a_key(api: Api) -> None:
    response = await api.client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
    assert api.portal_calls() == 0


async def test_health_answers_even_when_nothing_is_configured(make_api: MakeApi) -> None:
    api = await make_api(accounts={})
    (api.harness.state_dir / FILE_NAME).unlink()
    assert (await api.client.get("/healthz")).status_code == 200


async def test_ready_when_an_account_a_key_and_a_state_directory_exist(api: Api) -> None:
    response = await api.client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": READY}
    assert api.portal_calls() == 0


async def test_readiness_reports_nothing_but_the_checks(api: Api) -> None:
    body = (await api.client.get("/readyz")).json()
    assert set(body) == {"status", "checks"}


async def test_not_ready_without_an_account(make_api: MakeApi) -> None:
    api = await make_api(accounts={})
    response = await api.client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {**READY, "accounts": "failed"}}


async def test_not_ready_without_a_key(api: Api) -> None:
    api.keys.revoke("reader")
    api.keys.revoke("admin")
    response = await api.client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"] == {**READY, "keys": "failed"}


async def test_not_ready_when_the_key_file_cannot_be_read(api: Api) -> None:
    (api.harness.state_dir / FILE_NAME).write_text("not json", encoding="utf-8")
    response = await api.client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["keys"] == "failed"


async def test_a_state_directory_that_does_not_exist_yet_is_fine_when_it_can_be_made(
    api: Api,
) -> None:
    shutil.rmtree(api.harness.state_dir)
    response = await api.client.get("/readyz")
    assert response.json()["checks"]["state_dir"] == "ok"


async def test_a_state_directory_that_is_a_file_is_not_ready(api: Api) -> None:
    shutil.rmtree(api.harness.state_dir)
    api.harness.state_dir.write_text("in the way", encoding="utf-8")
    response = await api.client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["state_dir"] == "failed"
