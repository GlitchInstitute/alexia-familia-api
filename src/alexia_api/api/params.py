"""Path and query parameters that several routes share, and the cache headers they set.

A key that may not use an account gets the same 404 as a name that does not exist, so a key can
not be used to find out which accounts a server holds.
"""

from collections.abc import Awaitable, Callable
from functools import cache
from typing import Annotated, Any, Final

from fastapi import Depends, Path, Query, Response

from alexia_api.api.auth import require
from alexia_api.api.deps import ServicesDep
from alexia_api.domain.children import Child
from alexia_api.domain.security import Principal, Scope
from alexia_api.services.cache import Cached
from alexia_api.services.errors import NotFoundError
from alexia_api.services.registry import AccountRuntime

FreshQuery = Annotated[
    bool,
    Query(
        description=(
            "Ignore the stored answer and ask the portal again. The server still paces its "
            "requests, so use this when you know something changed and not on a timer."
        )
    ),
]

CACHE_HEADERS: Final[dict[int | str, dict[str, Any]]] = {
    200: {
        "headers": {
            "X-Cache": {
                "description": (
                    "`hit` when the answer was stored, `miss` when it was just read from the "
                    "portal, `bypass` when `fresh=true` forced a new read."
                ),
                "schema": {"type": "string", "enum": ["hit", "miss", "bypass"]},
            },
            "Age": {
                "description": "How many seconds old the answer is.",
                "schema": {"type": "integer", "minimum": 0},
            },
        }
    }
}


@cache
def account_for(scope: Scope) -> Callable[..., Awaitable[AccountRuntime]]:
    """A dependency that finds the account in the path, if the key holds `scope` and may use it."""

    async def resolve(
        account: Annotated[
            str, Path(description="The account's name, as the operator wrote it in the settings.")
        ],
        principal: Annotated[Principal, Depends(require(scope))],
        services: ServicesDep,
    ) -> AccountRuntime:
        if not principal.sees(account):
            raise NotFoundError("account", account)
        return services.registry.get(account)

    return resolve


ReadAccount = Annotated[AccountRuntime, Depends(account_for("read"))]
AdminAccount = Annotated[AccountRuntime, Depends(account_for("admin"))]


async def _found_child(
    child: Annotated[
        str,
        Path(
            description=(
                "A student id, or the child's slug as the list of children shows it. "
                "Letter case does not matter."
            )
        ),
    ],
    account: ReadAccount,
) -> Cached[Child]:
    return await account.child(child)


FoundChild = Annotated[Cached[Child], Depends(_found_child)]


def stamp(response: Response, cached: Cached[Any]) -> None:
    """Tell the client how the answer was found."""
    response.headers["X-Cache"] = cached.status
    response.headers["Age"] = str(int(cached.age))
