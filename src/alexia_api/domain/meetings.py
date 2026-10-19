"""Meetings between a guardian and the school, and the hours that a person offers for one."""

from typing import Final, Literal, get_args

from pydantic import AwareDatetime, Field

from alexia_api.domain.base import Model
from alexia_api.domain.ids import MeetingId

MeetingState = Literal["requested", "accepted", "cancelled", "declined", "done", "unknown"]
MEETING_STATES: Final[tuple[MeetingState, ...]] = get_args(MeetingState)


class Meeting(Model):
    """A meeting about one child that the portal lists, past, planned, or asked for."""

    id: MeetingId = Field(description="The portal's meeting id.")
    state: MeetingState = Field(
        description=(
            "Where the meeting stands. `requested` waits for an answer, `accepted` is agreed, "
            "`cancelled` and `declined` will not take place, and `done` took place. `unknown` "
            "means that the portal used a word this server does not know, so read `state_label`."
        )
    )
    state_label: str = Field(
        description="The portal's own word for the state, such as `Aceptada`, as it prints it."
    )
    starts_at: AwareDatetime = Field(
        description=(
            "When the meeting starts, with the school's offset. A meeting held for a whole group "
            "can show 00:00 here and put the time of day in `note`."
        )
    )
    requested_by: str | None = Field(
        description="Who asked for the meeting, as the portal prints it, or null."
    )
    staff: str | None = Field(
        description="The person at the school who is responsible for the meeting, or null."
    )
    note: str | None = Field(description="The note of the meeting, or null when there is none.")


class AvailableSlot(Model):
    """A stretch of time that a member of the staff offers for a meeting."""

    starts_at: AwareDatetime = Field(description="When the slot starts, with the school's offset.")
    ends_at: AwareDatetime = Field(description="When the slot ends, with the school's offset.")
