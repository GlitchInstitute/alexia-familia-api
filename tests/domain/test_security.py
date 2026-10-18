"""A key carries scopes that imply one another, and it may be limited to some accounts."""

import pytest
from pydantic import ValidationError

from alexia_api.domain.security import ALL_ACCOUNTS, SCOPES, Principal, Scope


def principal(*scopes: Scope, accounts: tuple[str, ...] = (ALL_ACCOUNTS,)) -> Principal:
    return Principal(key_name="home", scopes=frozenset(scopes), accounts=frozenset(accounts))


@pytest.mark.parametrize(
    ("held", "allowed"),
    [
        ("admin", {"admin", "write", "read", "feed"}),
        ("write", {"write", "read", "feed"}),
        ("read", {"read", "feed"}),
        ("feed", {"feed"}),
    ],
)
def test_each_scope_implies_the_ones_below_it(held: Scope, allowed: set[Scope]) -> None:
    key = principal(held)

    assert {scope for scope in SCOPES if key.allows(scope)} == allowed


def test_a_key_with_several_scopes_gets_the_union() -> None:
    key = principal("feed", "write")

    assert {scope for scope in SCOPES if key.allows(scope)} == {"write", "read", "feed"}


def test_only_a_key_that_holds_nothing_but_feed_may_travel_in_a_url() -> None:
    assert principal("feed").feed_only is True
    assert principal("feed", "read").feed_only is False
    assert principal("read").feed_only is False


def test_a_key_for_all_accounts_sees_any_account() -> None:
    assert principal("read").sees("marta") is True
    assert principal("read").sees("anyone-else") is True


def test_a_key_for_some_accounts_sees_only_those() -> None:
    key = principal("read", accounts=("marta",))

    assert key.sees("marta") is True
    assert key.sees("pablo") is False


@pytest.mark.parametrize(
    "bad",
    [
        {"scopes": frozenset(), "accounts": frozenset({"*"})},
        {"scopes": frozenset({"read"}), "accounts": frozenset()},
        {"scopes": frozenset({"root"}), "accounts": frozenset({"*"})},
    ],
)
def test_a_key_needs_a_known_scope_and_at_least_one_account(bad: dict[str, frozenset[str]]) -> None:
    with pytest.raises(ValidationError):
        Principal(key_name="home", **bad)  # type: ignore[arg-type]
