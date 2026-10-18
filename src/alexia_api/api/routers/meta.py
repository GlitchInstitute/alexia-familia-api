"""Routes that say whether the server is up and where things are. None of them needs a key."""

from typing import Literal

from fastapi import APIRouter, Response

from alexia_api import __version__
from alexia_api.api.deps import Services, ServicesDep
from alexia_api.api.schemas import Health, Index, Readiness
from alexia_api.services.health import state_dir_writable
from alexia_api.services.keys import ApiKeyStore, KeyStoreError

router = APIRouter(tags=["meta"])

type Check = Literal["ok", "failed"]


def _keys_check(keys: ApiKeyStore) -> Check:
    try:
        return "ok" if keys.records() else "failed"
    except KeyStoreError:
        return "failed"


def readiness_checks(services: Services) -> dict[str, Check]:
    return {
        "accounts": "ok" if services.registry.accounts else "failed",
        "keys": _keys_check(services.keys),
        "state_dir": "ok" if state_dir_writable(services.settings.state_dir) else "failed",
    }


@router.get(
    "/",
    summary="Describe this server",
    description="Names the server and says where its documentation and health checks are.",
)
async def index(services: ServicesDep) -> Index:
    docs_on = services.settings.docs_enabled
    return Index(
        name="alexia-familia-api",
        version=__version__,
        docs="/docs" if docs_on else None,
        openapi="/openapi.json" if docs_on else None,
        health="/healthz",
    )


@router.get(
    "/healthz",
    summary="Report that the process is alive",
    description=(
        "Answers 200 whenever the process runs. It does not look at the portal, the accounts, "
        "or the key file, so a container can use it as a liveness check."
    ),
)
async def healthz() -> Health:
    return Health(status="ok", version=__version__)


@router.get(
    "/readyz",
    summary="Report whether the server can serve requests",
    description=(
        "Answers 200 when at least one account and at least one API key are configured, the key "
        "file can be read, and the state directory is writable. Otherwise it answers 503 and "
        "names the checks that failed. It never calls the portal."
    ),
    responses={503: {"model": Readiness, "description": "At least one check failed."}},
)
async def readyz(services: ServicesDep, response: Response) -> Readiness:
    checks = readiness_checks(services)
    ready = all(result == "ok" for result in checks.values())
    if not ready:
        response.status_code = 503
    return Readiness(status="ready" if ready else "not_ready", checks=checks)
