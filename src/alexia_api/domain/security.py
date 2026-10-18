"""Who may do what.

An API key holds scopes. A scope is a kind of access, and a stronger scope includes the weaker
ones. The `feed` scope stands apart, because a calendar app cannot send a header and so the key
travels in a URL. A key that only opens calendar feeds does little harm when a URL leaks.
"""

from collections.abc import Mapping
from typing import Final, Literal, get_args

from pydantic import Field

from alexia_api.domain.base import Model

Scope = Literal["read", "write", "admin", "feed"]
SCOPES: Final[tuple[Scope, ...]] = get_args(Scope)
ALL_ACCOUNTS: Final = "*"

_IMPLIES: Final[Mapping[Scope, frozenset[Scope]]] = {
    "admin": frozenset({"admin", "write", "read", "feed"}),
    "write": frozenset({"write", "read", "feed"}),
    "read": frozenset({"read", "feed"}),
    "feed": frozenset({"feed"}),
}


class Principal(Model):
    """Who is calling, as far as the server can tell."""

    key_name: str = Field(description="The name the operator gave the key. It is safe to log.")
    scopes: frozenset[Scope] = Field(min_length=1, description="The kinds of access the key holds.")
    accounts: frozenset[str] = Field(
        min_length=1, description='The accounts the key may use, or "*" for every account.'
    )

    def allows(self, needed: Scope) -> bool:
        """Whether any scope the key holds is the needed one or includes it."""
        return any(needed in _IMPLIES[held] for held in self.scopes)

    def sees(self, account: str) -> bool:
        return ALL_ACCOUNTS in self.accounts or account in self.accounts

    @property
    def feed_only(self) -> bool:
        """Whether the key may be sent in a URL, which only a calendar-only key may."""
        return self.scopes == {"feed"}
