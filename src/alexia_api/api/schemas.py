"""The shapes of the responses that are not already domain models.

Every list is an object with an `items` array, so a field can be added next to it later without
breaking a client.
"""

from datetime import date
from typing import Literal

from pydantic import ConfigDict, Field

from alexia_api.domain.absences import Absence
from alexia_api.domain.accounts import Account
from alexia_api.domain.agenda import AgendaEvent
from alexia_api.domain.base import Model
from alexia_api.domain.children import Child, StaffMember
from alexia_api.domain.meetings import AvailableSlot, Meeting
from alexia_api.domain.messages import Folder, MessageSummary


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


class AbsenceList(Model):
    """The attendance incidents the portal lists for one child, newest day first."""

    items: tuple[Absence, ...]


class MeetingList(Model):
    """The meetings the portal lists for one child, in the order they take place."""

    items: tuple[Meeting, ...]


class AvailableDays(Model):
    """The days of one month on which a member of the staff has a free hour."""

    month: str = Field(
        pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$",
        description=(
            "The month the list is for, written YYYY-MM. It is the current month at the school "
            "when the request named none."
        ),
    )
    items: tuple[date, ...] = Field(
        description=(
            "The days with at least one free hour, earliest first, each day once. Empty when "
            "nothing is free in that month."
        )
    )


class AvailableHours(Model):
    """The free slots of one member of the staff on one day."""

    day: date = Field(description="The day the list is for.")
    items: tuple[AvailableSlot, ...] = Field(
        description="The free slots, earliest first. Empty when nothing is free on that day."
    )


class FolderList(Model):
    items: tuple[Folder, ...]


class MessagePage(Model):
    """One page of the messages in a folder, newest first."""

    items: tuple[MessageSummary, ...]
    total: int = Field(
        description=(
            "How many messages match, counting every page. It counts the messages this server "
            "holds, which is fewer than the portal lists when `truncated` is true."
        )
    )
    limit: int = Field(description="The page size that was asked for.")
    offset: int = Field(description="How many matching messages come before this page.")
    next_offset: int | None = Field(
        description="The offset to ask for the next page, or null on the last page."
    )
    truncated: bool = Field(
        description=(
            "True when the folder is longer than this server reads. The newest messages are "
            "here and the oldest are left out."
        )
    )


class Agenda(Model):
    """The entries of an agenda over a range of days, in the order they happen."""

    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(
        alias="from",
        description="The first day of the range, inclusive. It is the day that was asked for.",
    )
    to: date = Field(description="The last day of the range, inclusive.")
    items: tuple[AgendaEvent, ...] = Field(
        description="The entries that touch the range, earliest first, with the kinds asked for."
    )


class ConnectionCheck(Model):
    """The result of making sure the account has a working portal session."""

    session: Literal["new", "reused"] = Field(
        description="Whether the server had to log in, or the session it had still worked."
    )
    child_count: int | None = Field(description="How many children the login lists.")


class ConnectionReset(Model):
    """The result of lifting a block."""

    was_blocked: bool = Field(description="Whether logins had been paused before the reset.")
