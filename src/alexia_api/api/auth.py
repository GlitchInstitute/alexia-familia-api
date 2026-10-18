"""Who is calling, and whether they may do this.

A key travels as `Authorization: Bearer <key>` or as `X-API-Key`. When both are present the
bearer token is the one that counts. A missing key and a wrong key get different codes, because
that tells a caller nothing it did not know. A key that has used up its minute gets a 429.
"""

import math
from collections.abc import Callable
from functools import cache
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from alexia_api.api.deps import ServicesDep
from alexia_api.api.errors import ApiError
from alexia_api.domain.security import Principal, Scope

CHALLENGE = {"WWW-Authenticate": 'Bearer realm="alexia-familia-api"'}

_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="BearerKey",
    description=(
        "An API key, sent as `Authorization: Bearer <key>`. Make one with `alexia-api keys create`."
    ),
)
_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    scheme_name="HeaderKey",
    description=(
        "An API key, sent in the `X-API-Key` header. "
        "Use it when a client cannot set `Authorization`."
    ),
)


async def authenticate(
    request: Request,
    services: ServicesDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    header_key: Annotated[str | None, Depends(_header)],
) -> Principal:
    """Find the caller from the key and charge the request to the key's rate limit."""
    presented = credentials.credentials if credentials is not None else header_key
    if not presented:
        raise ApiError(
            401,
            "missing_api_key",
            "send your API key as 'Authorization: Bearer <key>' or in the X-API-Key header",
            headers=CHALLENGE,
        )
    principal = services.keys.authenticate(presented)
    if principal is None:
        raise ApiError(
            401,
            "invalid_api_key",
            "this API key is not valid, it may have been revoked",
            headers=CHALLENGE,
        )
    request.state.key_name = principal.key_name
    wait = services.limiter.check(principal.key_name)
    if wait is not None:
        seconds = max(1, math.ceil(wait))
        raise ApiError(
            429,
            "rate_limited",
            f"this key made too many requests, try again in {seconds} seconds",
            headers={"Retry-After": str(seconds)},
            retry_after_seconds=seconds,
        )
    return principal


@cache
def require(scope: Scope) -> Callable[[Principal], Principal]:
    """A dependency that passes the caller on when their key holds `scope`."""

    def check(principal: Annotated[Principal, Depends(authenticate)]) -> Principal:
        if not principal.allows(scope):
            raise ApiError(
                403,
                "insufficient_scope",
                f"this key does not hold the {scope} scope that this call needs",
                needed=scope,
            )
        return principal

    return check
