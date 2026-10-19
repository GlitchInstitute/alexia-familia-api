"""The application factory."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final

from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware
from starlette.types import Lifespan

from alexia_api import __version__
from alexia_api.api.deps import Services
from alexia_api.api.errors import install_handlers, refuse_host
from alexia_api.api.middleware import ListedHosts, RequestContext
from alexia_api.api.openapi import install_openapi
from alexia_api.api.routers import absences, accounts, agenda, children, messages, meta
from alexia_api.clock import Clock, SystemClock
from alexia_api.config import Settings, find_config_file, load_settings
from alexia_api.services.keys import FILE_NAME, ApiKeyStore
from alexia_api.services.ratelimit import RateLimiter
from alexia_api.services.registry import Registry

log = logging.getLogger("alexia_api.server")

DOCUMENTATION_PATHS: Final = ("/docs", "/redoc", "/docs/oauth2-redirect")

DESCRIPTION: Final = """\
An unofficial JSON API for the Alexia Familia parent portal. You run it yourself. It signs in to \
your own account and serves what the school shows you about your children.

**Keys.** Send an API key as `Authorization: Bearer <key>` or in the `X-API-Key` header. Make keys \
with `alexia-api keys create`. A key holds scopes (`read`, `write`, `admin`, `feed`) and a list of \
accounts it may use. The calendar feeds also take a key that holds only the `feed` scope as \
`?key=`, because a calendar app cannot send a header.

**Caching.** The server keeps each answer for a short time so that it stays gentle with the \
school's system. The `X-Cache` and `Age` headers say how an answer was found. Add `fresh=true` to \
ask the portal again.

**Errors.** Every failure is an RFC 9457 problem document with a stable `code` and a \
`request_id`. A 503 means the account cannot be used until the operator acts, for example after \
a wrong password. A 502 or a 504 means the portal misbehaved or did not answer.
"""

TAGS: Final = [
    {"name": "meta", "description": "Is the server up, and where is everything."},
    {"name": "accounts", "description": "The portal accounts this server holds, and their state."},
    {"name": "children", "description": "The children of an account and their school data."},
    {
        "name": "absences",
        "description": "The absences and other attendance incidents the portal lists for a child.",
    },
    {
        "name": "agenda",
        "description": (
            "The lessons, interviews, and school events of each child and of the guardian, as "
            "data and as calendar files that a calendar app can subscribe to."
        ),
    },
    {
        "name": "messages",
        "description": "The message folders of an account and the messages in them.",
    },
]


def _operation_id(route: APIRoute) -> str:
    return route.name


def _startup_line(settings: Settings, registry: Registry) -> str:
    accounts = ", ".join(runtime.account for runtime in registry.accounts) or "none"
    writes = "on" if settings.allow_writes else "off"
    documentation = "on" if settings.docs_enabled else "off"
    return (
        f"alexia-familia-api {__version__} is up, accounts {accounts}, "
        f"writes {writes}, documentation {documentation}"
    )


def _declare(lifespan: Lifespan[FastAPI] | None, pages: dict[str, Any]) -> FastAPI:
    """The app with its routes, its error handling, and its documentation, and no services yet.

    The routes find their services through the request, so nothing here needs a setting.
    """
    app = FastAPI(
        title="alexia-familia-api",
        version=__version__,
        summary="A REST API for the Alexia Familia parent portal",
        description=DESCRIPTION,
        openapi_tags=TAGS,
        lifespan=lifespan,
        generate_unique_id_function=_operation_id,
        **pages,
    )
    install_handlers(app)
    app.include_router(meta.router)
    app.include_router(accounts.router)
    app.include_router(children.router)
    app.include_router(absences.router)
    app.include_router(agenda.router)
    app.include_router(messages.router)
    install_openapi(app)
    return app


def openapi_document() -> dict[str, Any]:
    """The OpenAPI document of the server. No setting changes it, so no configuration is read."""
    return _declare(None, {}).openapi()


def create_app(
    settings: Settings | None = None,
    *,
    registry: Registry | None = None,
    keys: ApiKeyStore | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    """Build the server.

    With no arguments it reads the configuration file named by `ALEXIA_API_CONFIG`, or found in
    the working directory, together with the `ALEXIA_API_` variables. That is what `uvicorn
    --factory` calls. Tests pass their own parts.
    """
    clock = SystemClock() if clock is None else clock
    if settings is None:
        settings = load_settings(find_config_file(os.environ))
    if registry is None:
        registry = Registry.build(settings, environ=os.environ, clock=clock)
    if keys is None:
        keys = ApiKeyStore(settings.state_dir / FILE_NAME, clock)
    services = Services(
        settings=settings,
        registry=registry,
        keys=keys,
        limiter=RateLimiter(settings.rate_limit_per_minute, clock),
        clock=clock,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        log.info(_startup_line(settings, services.registry))
        try:
            yield
        finally:
            await services.registry.aclose()

    pages: dict[str, Any] = (
        {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
        if settings.docs_enabled
        else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    )
    app = _declare(lifespan, pages)
    app.state.services = services

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "X-API-Key", "Content-Type", "X-Request-Id"],
            expose_headers=["X-Request-Id", "X-Cache", "Age", "Retry-After"],
            max_age=600,
        )
    if settings.allowed_hosts:
        app.add_middleware(
            ListedHosts,
            allowed_hosts=settings.allowed_hosts,
            probe_paths=meta.PROBE_PATHS,
            refuse=refuse_host,
        )
    app.add_middleware(RequestContext, page_paths=DOCUMENTATION_PATHS)
    return app
