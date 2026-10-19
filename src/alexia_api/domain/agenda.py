"""The school agenda, as lessons, interviews, holidays, and other school events."""

from typing import Final, Literal, get_args

from pydantic import AwareDatetime, Field

from alexia_api.domain.base import Model

EventKind = Literal["lesson", "interview", "holiday", "school_event"]
EVENT_KINDS: Final[tuple[EventKind, ...]] = get_args(EventKind)

AgendaScope = Literal["child", "guardian"]


class LessonSignals(Model):
    """What the school flags on one lesson. A zero or a false means that nothing is flagged."""

    tasks: int = Field(ge=0, description="Homework and tasks tied to the lesson.")
    activities: int = Field(ge=0, description="Activities tied to the lesson.")
    notes: int = Field(ge=0, description="Teacher notes tied to the lesson.")
    tests: int = Field(ge=0, description="Tests and quizzes tied to the lesson.")
    substitution: bool = Field(description="True when a substitute teacher takes the lesson.")


class AgendaEvent(Model):
    """One entry of the school agenda."""

    id: str = Field(
        min_length=1,
        description=(
            "Names this occurrence and no other. The portal gives a lesson the same id every "
            "week, so this id is the portal's id, a `|`, and the day, as in `<id>|2026-10-19`."
        ),
    )
    kind: EventKind = Field(
        description=(
            "`lesson` for a lesson of the timetable, `interview` for a meeting with a teacher, "
            "`holiday` for a school event that the school titles `festivo`, and `school_event` "
            "for everything else the school puts in the agenda."
        )
    )
    title: str = Field(description="The title as the school writes it, in the school's language.")
    teacher: str | None = Field(
        description="The teacher the portal names for the entry, or null when it names none."
    )
    starts_at: AwareDatetime = Field(
        description=(
            "When the entry starts, with the school's offset. The portal writes local time and "
            "marks it as UTC by mistake, and this server puts the right offset on it."
        )
    )
    ends_at: AwareDatetime = Field(description="When the entry ends, with the school's offset.")
    all_day: bool = Field(
        description=(
            "True when the entry covers whole days. The portal gives such an entry the times "
            "00:00 and 00:00 or 23:59, and the days it covers run from `starts_at` to `ends_at`."
        )
    )
    signals: LessonSignals | None = Field(
        description="What the school flags on a lesson. Null for any other kind of entry."
    )
