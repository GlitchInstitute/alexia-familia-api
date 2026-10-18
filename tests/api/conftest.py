"""Fixtures that run the real application against the simulator, in process."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from typing import Any

import httpx
import pytest

from alexia_api.api.app import create_app
from alexia_api.services.keys import FILE_NAME, ApiKeyStore
from tests.api.support import Api, MakeApi
from tests.harness import Harness

BASE_URL = "http://api.test"


@pytest.fixture
async def make_api(harness: Harness) -> AsyncIterator[MakeApi]:
    """Build an application. Keyword arguments become settings, so a test can change any of them."""
    async with AsyncExitStack() as stack:

        async def make(**overrides: Any) -> Api:
            settings = harness.settings(**overrides)
            keys = ApiKeyStore(settings.state_dir / FILE_NAME, harness.clock)
            read = keys.create("reader", scopes=["read"], accounts=["*"])
            admin = keys.create("admin", scopes=["admin"], accounts=["*"])
            app = create_app(
                settings, registry=harness.registry(settings), keys=keys, clock=harness.clock
            )
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            client = await stack.enter_async_context(
                httpx.AsyncClient(transport=transport, base_url=BASE_URL)
            )
            return Api(
                app=app,
                client=client,
                harness=harness,
                keys=keys,
                read_key=read.key,
                admin_key=admin.key,
            )

        yield make


@pytest.fixture
async def api(make_api: MakeApi) -> Api:
    return await make_api()
