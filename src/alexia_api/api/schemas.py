"""The shapes of the responses that are not already domain models.

Every list is an object with an `items` array, so a field can be added next to it later without
breaking a client.
"""

from typing import Literal

from pydantic import Field

from alexia_api.domain.accounts import Account
from alexia_api.domain.base import Model
from alexia_api.domain.children import Child, StaffMember


class Index(Model):
    """Where things are on this server."""

    name: str
    version: str
    docs: str | None = Field(description="The interactive documentation, or null when it is off.")
    openapi: str | None = Field(description="The OpenAPI document, or null when it is off.")
    health: str = Field(description="The liveness check.")


class Health(Model):
    """The process is up. This says nothing about the portal."""

    status: Literal["ok"]
    version: str


class Readiness(Model):
    """Whether the server can serve requests. It never calls the portal."""

    status: Literal["ready", "not_ready"]
    checks: dict[str, Literal["ok", "failed"]] = Field(
        description="One entry per thing that was checked."
    )


class AccountList(Model):
    items: tuple[Account, ...]


class ChildList(Model):
    items: tuple[Child, ...]


class StaffList(Model):
    items: tuple[StaffMember, ...]


class ConnectionCheck(Model):
    """The result of making sure the account has a working portal session."""

    session: Literal["new", "reused"] = Field(
        description="Whether the server had to log in, or the session it had still worked."
    )
    child_count: int | None = Field(description="How many children the login lists.")


class ConnectionReset(Model):
    """The result of lifting a block."""

    was_blocked: bool = Field(description="Whether logins had been paused before the reset.")
