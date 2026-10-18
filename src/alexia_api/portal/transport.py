"""One HTTP exchange with the portal, with hard limits and typed failures."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

import httpx

from alexia_api.domain.errors import PortalError, Transport

DEFAULT_USER_AGENT: Final = "alexia-familia-api (a personal tool run by a guardian)"
DEFAULT_TIMEOUT_SECONDS: Final = 30.0
DEFAULT_MAX_BYTES: Final = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class RawResponse:
    status: int
    headers: httpx.Headers
    body: bytes


async def exchange(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    content: bytes | None,
    max_bytes: int,
) -> RawResponse:
    """Send one request without following redirects and read at most `max_bytes` of the body.

    The limit counts decoded bytes, so a compressed bomb is stopped the same way as a long page.
    """
    try:
        async with client.stream(method, url, headers=headers, content=content) as response:
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise PortalError(Transport(reason="too_large"))
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise PortalError(Transport(reason="too_large"))
                chunks.append(chunk)
            return RawResponse(response.status_code, response.headers, b"".join(chunks))
    except httpx.TimeoutException as error:
        raise PortalError(Transport(reason="timeout")) from error
    except httpx.RequestError as error:
        raise PortalError(Transport(reason="network")) from error
