"""Accounts and the state of their connection to the portal."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from alexia_api.domain.base import Model
from alexia_api.domain.errors import BREAKER_CAUSE_TEXT, BreakerCause, Interstitial
from alexia_api.domain.ids import AccountId


class LoggedOut(Model):
    """No session is open. The next request that needs the portal logs in first."""

    state: Literal["logged_out"] = "logged_out"


class LoggedIn(Model):
    """A session is open and the portal answered it recently."""

    state: Literal["logged_in"] = "logged_in"
    since: AwareDatetime = Field(description="When this session logged in.")
    last_success_at: AwareDatetime = Field(description="When the portal last answered a call.")


class Blocked(Model):
    """Automatic logins are paused until an operator resets the block.

    A wrong password can lock a guardian's account, so the server stops after the first login
    failure that could do that and waits for a person to fix the cause.
    """

    state: Literal["blocked"] = "blocked"
    cause: BreakerCause = Field(description="The failure that paused automatic logins.")
    since: AwareDatetime = Field(description="When the block started.")
    interstitial: Interstitial | None = Field(
        default=None,
        description="The portal page that needs a person, when the cause is a required step.",
    )

    def when_and_why(self) -> str:
        """When the block began and why, worded to follow the words `logins are paused`."""
        return f"since {self.since:%Y-%m-%d %H:%M %z} because {BREAKER_CAUSE_TEXT[self.cause]}"


Connection = Annotated[LoggedOut | LoggedIn | Blocked, Field(discriminator="state")]


class Capabilities(Model):
    """What the operator switched on for an account."""

    writes: bool = Field(
        description="Messages and meeting requests may be sent through the outbox."
    )
    forms: bool = Field(description="Forms may be answered. This needs writes as well.")
    restore_unread: bool = Field(
        description="A message opened through the API is put back to unread at the portal."
    )


class Account(Model):
    """One set of portal credentials. It holds the children that the portal lists for it."""

    id: AccountId = Field(description="The account's short name in URLs, chosen by the operator.")
    label: str = Field(
        description=(
            "A name for people, for example the guardian's first name. It also names the family "
            "calendar and the guardian calendar."
        )
    )
    portal_host: str = Field(description="The host name of the portal this account signs in to.")
    connection: Connection
    capabilities: Capabilities
    child_count: int | None = Field(
        description="Children seen at the last login, or null before the first login."
    )
