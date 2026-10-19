"""The agenda models refuse the values that the rest of the server relies on never seeing."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from alexia_api.domain.agenda import EVENT_KINDS, AgendaEvent, LessonSignals

MADRID = ZoneInfo("Europe/Madrid")
NO_FLAGS = {"tasks": 0, "activities": 0, "notes": 0, "tests": 0, "substitution": False}


def an_event(**changes: object) -> AgendaEvent:
    fields: dict[str, object] = {
        "id": "a|2026-03-02",
        "kind": "lesson",
        "title": "Música",
        "teacher": None,
        "starts_at": datetime(2026, 3, 2, 9, 0, tzinfo=MADRID),
        "ends_at": datetime(2026, 3, 2, 9, 45, tzinfo=MADRID),
        "all_day": False,
        "signals": None,
    }
    return AgendaEvent.model_validate({**fields, **changes})


def test_the_kinds_of_entry_are_the_four_the_api_names_in_this_order() -> None:
    assert EVENT_KINDS == ("lesson", "interview", "holiday", "school_event")


@pytest.mark.parametrize("name", ["tasks", "activities", "notes", "tests"])
def test_a_counter_cannot_be_negative(name: str) -> None:
    with pytest.raises(ValidationError):
        LessonSignals.model_validate({**NO_FLAGS, name: -1})


def test_a_substitution_is_a_yes_or_a_no() -> None:
    assert LessonSignals.model_validate({**NO_FLAGS, "substitution": True}).substitution is True
    with pytest.raises(ValidationError):
        LessonSignals.model_validate({**NO_FLAGS, "substitution": "maybe"})


def test_an_entry_needs_a_known_kind() -> None:
    assert an_event(kind="holiday").kind == "holiday"
    with pytest.raises(ValidationError):
        an_event(kind="exam")


def test_an_entry_needs_an_id_and_times_that_name_their_zone() -> None:
    with pytest.raises(ValidationError):
        an_event(id="")
    with pytest.raises(ValidationError):
        an_event(starts_at=datetime(2026, 3, 2, 9, 0))
    with pytest.raises(ValidationError):
        an_event(ends_at=datetime(2026, 3, 2, 9, 45))


def test_the_models_are_frozen_and_refuse_unknown_fields() -> None:
    event = an_event()

    with pytest.raises(ValidationError):
        event.title = "Other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        an_event(room="12")
    with pytest.raises(ValidationError):
        LessonSignals.model_validate({**NO_FLAGS, "homework": 1})


def test_an_entry_serialises_with_the_offset_the_school_has() -> None:
    event = an_event()

    assert event.model_dump(mode="json")["starts_at"] == "2026-03-02T09:00:00+01:00"
