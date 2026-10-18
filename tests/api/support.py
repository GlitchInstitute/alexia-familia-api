"""What the API tests share, apart from the fixtures."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI

from alexia_api.services.keys import ApiKeyStore
from tests.harness import Harness

PROBLEM_MEDIA_TYPE = "application/problem+json"


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def problem_of(response: httpx.Response, *, status: int, code: str) -> dict[str, Any]:
    """The problem document in a response, after checking what every problem has in common."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body: dict[str, Any] = response.json()
    assert body["code"] == code
    assert body["status"] == status
    assert body["type"] == "about:blank"
    assert body["request_id"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"
    return body


@dataclass
class Api:
    """A running application, a client for it, and two keys that open it."""

    app: FastAPI
    client: httpx.AsyncClient
    harness: Harness
    keys: ApiKeyStore
    read_key: str
    admin_key: str

    async def get(
        self,
        path: str,
        *,
        key: str | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        sent = {**bearer(key or self.read_key), **(headers or {})}
        return await self.client.get(path, headers=sent, **kwargs)

    async def post(
        self,
        path: str,
        *,
        key: str | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        sent = {**bearer(key or self.read_key), **(headers or {})}
        return await self.client.post(path, headers=sent, **kwargs)

    def portal_calls(self) -> int:
        return len(self.harness.sim.requests)


type MakeApi = Callable[..., Awaitable[Api]]
