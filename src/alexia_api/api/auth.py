"""Who is calling, and whether they may do this.

A key travels as `Authorization: Bearer <key>` or as `X-API-Key`. When both are present the
bearer token is the one that counts. A missing key and a wrong key get different codes, because
that tells a caller nothing it did not know. A key that has used up its minute gets a 429.

A calendar app cannot send a header, so the calendar feeds also take a key in the `key` query
parameter. A URL is copied into settings, chat messages, and browser history, so only a key that
holds nothing but the `feed` scope may travel there. A key with any other scope is refused in a
URL even when it is valid, which keeps a leaked feed address from opening anything but a calendar.
"""

import math
from collections.abc import Callable
from functools import cache
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, APIKeyQuery, HTTPAuthorizationCredentials, HTTPBearer

from alexia_api.api.deps import Services, ServicesDep
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
_query = APIKeyQuery(
    name="key",
    auto_error=False,
    scheme_name="FeedKey",
    description=(
        "A key that holds only the `feed` scope, sent as `?key=<key>`. Use it for a calendar app "
        "that cannot set a header. Make one with `alexia-api keys create NAME --scope feed`. "
        "A key with any other scope is refused here."
    ),
)

HEADER_HINT = "send your API key as 'Authorization: Bearer <key>' or in the X-API-Key header"
FEED_HINT = (
    "send your API key as 'Authorization: Bearer <key>' or in the X-API-Key header, "
    "or send a key that holds only the feed scope as ?key=<key>"
)


def identify(
    request: Request, services: Services, presented: str | None, *, hint: str
) -> Principal:
    """Find the caller from the key and charge the request to the key's rate limit."""
    if not presented:
        raise ApiError(401, "missing_api_key", hint, headers=CHALLENGE)
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
        seconds = math.ceil(wait)
        raise ApiError(
            429,
            "rate_limited",
            f"this key made too many requests, try again in {seconds} seconds",
            headers={"Retry-After": str(seconds)},
            retry_after_seconds=seconds,
        )
    return principal


async def authenticate(
    request: Request,
    services: ServicesDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    header_key: Annotated[str | None, Depends(_header)],
) -> Principal:
    """Find the caller from a key in a header."""
    presented = credentials.credentials if credentials is not None else header_key
    return identify(request, services, presented, hint=HEADER_HINT)


async def authenticate_feed(
    request: Request,
    services: ServicesDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    header_key: Annotated[str | None, Depends(_header)],
    url_key: Annotated[str | None, Depends(_query)],
) -> Principal:
    """Find the caller from a key in a header or, for a feed key only, in the URL."""
    in_header = credentials.credentials if credentials is not None else header_key
    principal = identify(request, services, in_header or url_key, hint=FEED_HINT)
    if not in_header and not principal.feed_only:
        raise ApiError(
            403,
            "key_not_allowed_in_url",
            "a key in a URL must hold only the feed scope, so send this key in a header, "
            "or make a key for the calendar with `alexia-api keys create NAME --scope feed`",
        )
    return principal


def _holding(principal: Principal, scope: Scope) -> Principal:
    if not principal.allows(scope):
        raise ApiError(
            403,
            "insufficient_scope",
            f"this key does not hold the {scope} scope that this call needs",
            needed=scope,
        )
    return principal


@cache
def require(scope: Scope) -> Callable[[Principal], Principal]:
    """A dependency that passes the caller on when their key holds `scope`."""

    def check(principal: Annotated[Principal, Depends(authenticate)]) -> Principal:
        return _holding(principal, scope)

    return check


def require_feed(principal: Annotated[Principal, Depends(authenticate_feed)]) -> Principal:
    """A dependency for the calendar feeds, which need the feed scope that every other one holds."""
    return _holding(principal, "feed")
