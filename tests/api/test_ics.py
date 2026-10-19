import unicodedata
from datetime import UTC, date, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st
from icalendar import Event

from alexia_api.api.ics import (
    UNNAMED,
    CalendarEntry,
    CalendarSource,
    calendar_entries,
    describe,
    plain,
    render_calendar,
)
from alexia_api.domain.agenda import AgendaEvent, EventKind, LessonSignals
from tests.api.support import unfolded, vevents

MADRID = ZoneInfo("Europe/Madrid")
STAMP = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
NO_FLAGS = LessonSignals(tasks=0, activities=0, notes=0, tests=0, substitution=False)
EVERY_CHARACTER = st.characters(exclude_categories=())
ANY_TEXT = st.text(alphabet=EVERY_CHARACTER, max_size=200)


def lesson(
    day: date = date(2026, 1, 12),
    *,
    title: str = "Matemáticas",
    teacher: str | None = "Ana Muestra",
    signals: LessonSignals = NO_FLAGS,
    event_id: str = "lesson-1",
    hour: int = 9,
) -> AgendaEvent:
    starts = datetime(day.year, day.month, day.day, hour, 0, tzinfo=MADRID)
    return AgendaEvent(
        id=f"{event_id}|{day.isoformat()}",
        kind="lesson",
        title=title,
        teacher=teacher,
        starts_at=starts,
        ends_at=starts + timedelta(minutes=45),
        all_day=False,
        signals=signals,
    )


def occasion(
    title: str = "Entrevista",
    *,
    kind: EventKind = "interview",
    day: date = date(2026, 1, 13),
    hour: int = 16,
    minutes: int = 30,
    event_id: str = "occasion-1",
    teacher: str | None = None,
) -> AgendaEvent:
    starts = datetime(day.year, day.month, day.day, hour, 0, tzinfo=MADRID)
    return AgendaEvent(
        id=f"{event_id}|{day.isoformat()}",
        kind=kind,
        title=title,
        teacher=teacher,
        starts_at=starts,
        ends_at=starts + timedelta(minutes=minutes),
        all_day=False,
        signals=None,
    )


def all_day(
    title: str = "FESTIVO",
    first: date = date(2026, 3, 30),
    last: date | None = None,
    *,
    kind: EventKind = "holiday",
    ends_at_midnight: bool = False,
    event_id: str = "day-1",
) -> AgendaEvent:
    final = last or first
    ends = datetime(final.year, final.month, final.day, tzinfo=MADRID)
    if not ends_at_midnight:
        ends += timedelta(hours=23, minutes=59)
    return AgendaEvent(
        id=f"{event_id}|{first.isoformat()}",
        kind=kind,
        title=title,
        teacher=None,
        starts_at=datetime(first.year, first.month, first.day, tzinfo=MADRID),
        ends_at=ends,
        all_day=True,
        signals=None,
    )


def render(
    *events: AgendaEvent,
    name: str = "Test calendar",
    scope: str = "kid",
    label: str | None = None,
    stamped_at: datetime = STAMP,
) -> bytes:
    entries = calendar_entries([CalendarSource(scope, label, tuple(events))], shared="home")
    return render_calendar(name, entries, zone=MADRID, stamped_at=stamped_at)


def only_event(data: bytes) -> Event:
    [event] = vevents(data)
    return event


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("  two   spaces\tand\nbreaks ", "two spaces and breaks"),
        ("nul\x00byte", "nul byte"),
        ("line\u2028separator", "line separator"),
        ("paragraph\u2029separator", "paragraph separator"),
        ("no\u00a0break space", "no break space"),
        ("right to left\u202eoverride", "right to leftoverride"),
        ("zero\u200bwidth", "zerowidth"),
        ("\u200e\u200f", ""),
        ("", ""),
        ("   ", ""),
        ("Lucía: ñandú ✓ 😀", "Lucía: ñandú ✓ 😀"),
        ("lone \ud800 surrogate", "lone surrogate"),
    ],
)
def test_text_becomes_one_plain_line(text: str, shown: str) -> None:
    assert plain(text) == shown


@given(ANY_TEXT)
def test_plain_text_has_no_control_or_invisible_character_and_no_stray_space(text: str) -> None:
    shown = plain(text)
    assert not {unicodedata.category(char) for char in shown} & {"Cc", "Cf", "Cs", "Zl", "Zp"}
    assert shown == shown.strip()
    assert "  " not in shown
    assert plain(shown) == shown


@given(st.text(alphabet=st.characters(categories=["L", "N", "P", "S"]), max_size=60))
def test_text_made_only_of_visible_characters_is_left_as_it_is(text: str) -> None:
    assert plain(text) == text


def test_a_lesson_is_described_by_its_teacher() -> None:
    assert describe(lesson(teacher="Ana Muestra")) == "Teacher Ana Muestra."


@pytest.mark.parametrize("teacher", [None, "", "   ", "\u200b\u200e"])
def test_a_lesson_with_nothing_to_say_has_no_description(teacher: str | None) -> None:
    assert describe(lesson(teacher=teacher)) is None


@pytest.mark.parametrize(
    ("signals", "sentence"),
    [
        ((1, 0, 0, 0), "The school flagged 1 task."),
        ((2, 0, 0, 0), "The school flagged 2 tasks."),
        ((0, 1, 0, 0), "The school flagged 1 activity."),
        ((0, 3, 0, 0), "The school flagged 3 activities."),
        ((0, 0, 1, 0), "The school flagged 1 note."),
        ((0, 0, 0, 2), "The school flagged 2 tests."),
        ((1, 0, 0, 1), "The school flagged 1 task and 1 test."),
        ((1, 2, 0, 3), "The school flagged 1 task, 2 activities and 3 tests."),
        ((1, 1, 1, 1), "The school flagged 1 task, 1 activity, 1 note and 1 test."),
    ],
)
def test_what_the_school_flagged_is_told_in_one_sentence(
    signals: tuple[int, int, int, int], sentence: str
) -> None:
    tasks, activities, notes, tests = signals
    flagged = LessonSignals(
        tasks=tasks, activities=activities, notes=notes, tests=tests, substitution=False
    )
    assert describe(lesson(teacher=None, signals=flagged)) == sentence


def test_a_substitute_teacher_is_told_last() -> None:
    flagged = LessonSignals(tasks=1, activities=0, notes=0, tests=0, substitution=True)
    assert describe(lesson(signals=flagged)) == (
        "Teacher Ana Muestra.\nThe school flagged 1 task.\nA substitute teacher takes this lesson."
    )


def test_a_substitution_alone_is_still_told() -> None:
    substituted = LessonSignals(tasks=0, activities=0, notes=0, tests=0, substitution=True)
    assert describe(lesson(teacher=None, signals=substituted)) == (
        "A substitute teacher takes this lesson."
    )


@pytest.mark.parametrize("kind", ["interview", "holiday", "school_event"])
def test_only_a_lesson_has_a_description(kind: EventKind) -> None:
    assert describe(occasion(kind=kind, teacher="Ana Muestra")) is None


def test_the_teacher_of_a_lesson_is_cleaned_like_every_other_word() -> None:
    assert describe(lesson(teacher="Ana\r\nMuestra\u202e")) == "Teacher Ana Muestra."


def sources(
    first: tuple[AgendaEvent, ...], second: tuple[AgendaEvent, ...]
) -> list[CalendarSource]:
    return [CalendarSource("lucia", "Lucía", first), CalendarSource("mateo", "Mateo", second)]


def test_a_lesson_two_people_share_is_listed_for_each_of_them() -> None:
    together = lesson()
    entries = calendar_entries(sources((together,), (together,)), shared="home")
    assert [(entry.scope, entry.label) for entry in entries] == [
        ("lucia", "Lucía"),
        ("mateo", "Mateo"),
    ]


def test_an_entry_of_one_person_keeps_that_persons_scope_and_label() -> None:
    entries = calendar_entries(sources((occasion("Excursión"),), ()), shared="home")
    assert [(entry.scope, entry.label, entry.event.title) for entry in entries] == [
        ("lucia", "Lucía", "Excursión")
    ]


def test_an_occasion_two_people_share_is_listed_once_and_belongs_to_nobody() -> None:
    holiday = all_day()
    entries = calendar_entries(sources((holiday,), (holiday,)), shared="home")
    assert [(entry.scope, entry.label, entry.event.id) for entry in entries] == [
        ("home", None, holiday.id)
    ]


def test_the_first_person_to_hold_a_shared_occasion_decides_which_id_it_keeps() -> None:
    first = all_day(event_id="from-lucia")
    second = all_day(event_id="from-mateo")
    [entry] = calendar_entries(sources((first,), (second,)), shared="home")
    assert entry.event.id == first.id


def test_an_occasion_three_people_share_is_still_listed_once() -> None:
    holiday = all_day()
    three = [CalendarSource(name, name, (holiday,)) for name in ("a", "b", "c")]
    assert len(calendar_entries(three, shared="home")) == 1


def test_occasions_that_differ_in_time_are_not_the_same_occasion() -> None:
    entries = calendar_entries(sources((occasion(hour=16),), (occasion(hour=17),)), shared="home")
    assert [entry.scope for entry in entries] == ["lucia", "mateo"]


def test_occasions_that_differ_in_length_are_not_the_same_occasion() -> None:
    entries = calendar_entries(
        sources((occasion(minutes=30),), (occasion(minutes=45),)), shared="home"
    )
    assert [entry.scope for entry in entries] == ["lucia", "mateo"]


def test_occasions_that_differ_in_title_are_not_the_same_occasion() -> None:
    entries = calendar_entries(
        sources((occasion("Entrevista"),), (occasion("Reunión"),)), shared="home"
    )
    assert [entry.scope for entry in entries] == ["lucia", "mateo"]


def test_occasions_that_differ_in_kind_are_not_the_same_occasion() -> None:
    entries = calendar_entries(
        sources(
            (occasion("Salida", kind="school_event"),), (occasion("Salida", kind="interview"),)
        ),
        shared="home",
    )
    assert [entry.scope for entry in entries] == ["lucia", "mateo"]


def test_two_entries_of_one_person_that_look_alike_are_both_kept() -> None:
    twins = (occasion(event_id="one"), occasion(event_id="two"))
    entries = calendar_entries([CalendarSource("lucia", "Lucía", twins)], shared="home")
    assert [entry.event.id for entry in entries] == [twins[0].id, twins[1].id]


def test_no_sources_make_no_entries() -> None:
    assert calendar_entries([], shared="home") == []
    assert calendar_entries([CalendarSource("lucia", "Lucía", ())], shared="home") == []


def test_the_file_is_a_calendar_that_names_itself_and_its_zone() -> None:
    lines = unfolded(render(lesson(), name="Lucía school calendar"))
    assert lines[0] == "BEGIN:VCALENDAR"
    assert lines[-2:] == ["END:VCALENDAR", ""]
    for expected in (
        "VERSION:2.0",
        "PRODID:-//alexia-familia-api//School calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Lucía school calendar",
        "X-WR-TIMEZONE:Europe/Madrid",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ):
        assert expected in lines


def test_every_line_ends_with_a_carriage_return_and_a_line_feed() -> None:
    data = render(lesson(), all_day())
    assert data.endswith(b"\r\n")
    assert b"\n" not in data.replace(b"\r\n", b"")
    assert b"\r" not in data.replace(b"\r\n", b"")


def test_the_file_is_utf_8_and_keeps_accents_as_they_are() -> None:
    data = render(lesson(title="Educación Física"), name="Lucía")
    assert "Educación Física".encode() in data
    assert "X-WR-CALNAME:Lucía".encode() in data


def test_the_file_holds_no_rules_of_a_zone_for_an_app_to_misread() -> None:
    lines = unfolded(render(lesson(), occasion(), all_day()))
    assert "BEGIN:VTIMEZONE" not in lines
    assert not any("TZID" in line for line in lines)


def test_a_lesson_is_a_timed_event_with_its_teacher_in_the_description() -> None:
    event = only_event(render(lesson(day=date(2026, 1, 12))))
    assert str(event["SUMMARY"]) == "Matemáticas"
    assert str(event["DESCRIPTION"]) == "Teacher Ana Muestra."
    assert event.decoded("DTSTART") == datetime(2026, 1, 12, 9, 0, tzinfo=MADRID)
    assert event.decoded("DTEND") == datetime(2026, 1, 12, 9, 45, tzinfo=MADRID)
    assert "TRANSP" not in event


def test_a_timed_entry_is_one_instant_in_utc() -> None:
    lines = unfolded(render(lesson(day=date(2026, 1, 12))))
    assert "DTSTART:20260112T080000Z" in lines
    assert "DTEND:20260112T084500Z" in lines


def test_a_lesson_stays_at_nine_on_both_sides_of_a_clock_change() -> None:
    data = render(lesson(date(2026, 3, 27)), lesson(date(2026, 3, 30)))
    lines = unfolded(data)
    assert "DTSTART:20260327T080000Z" in lines
    assert "DTSTART:20260330T070000Z" in lines
    hours = [event.decoded("DTSTART").astimezone(MADRID).hour for event in vevents(data)]
    assert hours == [9, 9]


def test_an_entry_that_has_no_length_has_no_end() -> None:
    point = occasion(minutes=0)
    assert point.starts_at == point.ends_at
    event = only_event(render(point))
    assert "DTEND" not in event
    assert event.decoded("DTSTART") == point.starts_at


def test_an_entry_that_ends_before_it_starts_has_no_end() -> None:
    backwards = occasion().model_copy(
        update={"ends_at": datetime(2026, 1, 13, 15, 0, tzinfo=MADRID)}
    )
    assert "DTEND" not in only_event(render(backwards))


def test_an_all_day_entry_is_free_time_on_whole_days() -> None:
    event = only_event(render(all_day(first=date(2026, 3, 30))))
    assert event.decoded("DTSTART") == date(2026, 3, 30)
    assert event.decoded("DTEND") == date(2026, 3, 31)
    assert str(event["TRANSP"]) == "TRANSPARENT"


@pytest.mark.parametrize("ends_at_midnight", [True, False])
def test_both_ways_the_portal_ends_a_one_day_holiday_make_the_same_entry(
    ends_at_midnight: bool,
) -> None:
    event = only_event(render(all_day(ends_at_midnight=ends_at_midnight)))
    assert (event.decoded("DTSTART"), event.decoded("DTEND")) == (
        date(2026, 3, 30),
        date(2026, 3, 31),
    )


@pytest.mark.parametrize("ends_at_midnight", [True, False])
def test_the_last_day_of_an_all_day_run_is_included(ends_at_midnight: bool) -> None:
    run = all_day(
        first=date(2025, 12, 23), last=date(2026, 1, 7), ends_at_midnight=ends_at_midnight
    )
    event = only_event(render(run))
    assert event.decoded("DTSTART") == date(2025, 12, 23)
    assert event.decoded("DTEND") == date(2026, 1, 8)


def test_an_all_day_entry_that_ends_before_it_starts_lasts_one_day() -> None:
    holiday = all_day(first=date(2026, 3, 30))
    backwards = holiday.model_copy(update={"ends_at": datetime(2026, 3, 29, tzinfo=MADRID)})
    event = only_event(render(backwards))
    assert (event.decoded("DTSTART"), event.decoded("DTEND")) == (
        date(2026, 3, 30),
        date(2026, 3, 31),
    )


ARRIVAL_ZONES = [UTC, ZoneInfo("America/New_York"), ZoneInfo("Asia/Kolkata")]


def in_zone(event: AgendaEvent, zone: tzinfo) -> AgendaEvent:
    return event.model_copy(
        update={
            "starts_at": event.starts_at.astimezone(zone),
            "ends_at": event.ends_at.astimezone(zone),
        }
    )


@pytest.mark.parametrize("zone", ARRIVAL_ZONES)
def test_a_timed_entry_is_the_same_instant_in_whatever_zone_it_arrives(zone: tzinfo) -> None:
    arriving = in_zone(lesson(day=date(2026, 1, 12)), zone)
    assert render(arriving) == render(lesson(day=date(2026, 1, 12)))


@pytest.mark.parametrize("zone", ARRIVAL_ZONES)
def test_an_all_day_entry_given_in_another_zone_keeps_the_days_of_the_zone_of_the_file(
    zone: tzinfo,
) -> None:
    holiday = all_day(first=date(2026, 3, 30), last=date(2026, 3, 31))
    event = only_event(render(in_zone(holiday, zone)))
    assert (event.decoded("DTSTART"), event.decoded("DTEND")) == (
        date(2026, 3, 30),
        date(2026, 4, 1),
    )


def test_the_stamp_is_the_time_the_file_was_made_in_utc() -> None:
    lines = unfolded(render(lesson(), stamped_at=datetime(2026, 5, 6, 14, 30, tzinfo=MADRID)))
    assert "DTSTAMP:20260506T123000Z" in lines


def test_the_file_does_not_read_the_system_clock() -> None:
    first = render(lesson(), stamped_at=STAMP)
    second = render(lesson(), stamped_at=STAMP)
    later = render(lesson(), stamped_at=STAMP + timedelta(minutes=5))
    assert first == second
    assert first != later
    assert first.replace(b"20260101T120000Z", b"") == later.replace(b"20260101T120500Z", b"")


def test_an_entry_has_a_uid_that_names_its_scope_its_id_and_this_program() -> None:
    event = only_event(render(lesson(event_id="abc"), scope="kid"))
    assert str(event["UID"]) == "kid.abc|2026-01-12@alexia-familia-api"


def test_the_uid_of_an_entry_does_not_change_between_files() -> None:
    first = only_event(render(lesson(), stamped_at=STAMP))
    later = only_event(render(lesson(), stamped_at=STAMP + timedelta(days=3)))
    assert str(first["UID"]) == str(later["UID"])


def test_the_same_lesson_of_two_scopes_has_two_uids() -> None:
    entries = [
        entry
        for scope in ("lucia", "mateo")
        for entry in calendar_entries([CalendarSource(scope, None, (lesson(),))], shared="home")
    ]
    data = render_calendar("Both", entries, zone=MADRID, stamped_at=STAMP)
    assert len({str(event["UID"]) for event in vevents(data)}) == 2


def test_a_uid_holds_no_space_and_no_control_character() -> None:
    event = only_event(render(lesson(event_id="a b\r\nATTENDEE:evil"), scope="kid one"))
    assert str(event["UID"]) == "kid_one.a_bATTENDEE:evil|2026-01-12@alexia-familia-api"
    assert "ATTENDEE" not in event


def test_a_label_goes_in_front_of_the_title() -> None:
    event = only_event(render(lesson(title="Inglés"), label="Lucía"))
    assert str(event["SUMMARY"]) == "Lucía: Inglés"


def test_an_entry_without_a_title_shows_its_label() -> None:
    assert str(only_event(render(lesson(title=""), label="Lucía"))["SUMMARY"]) == "Lucía"


def test_an_entry_with_neither_title_nor_label_has_an_empty_summary() -> None:
    assert str(only_event(render(lesson(title="   ")))["SUMMARY"]) == ""


def test_the_name_of_the_calendar_falls_back_when_it_is_empty() -> None:
    assert f"X-WR-CALNAME:{UNNAMED}" in unfolded(render(lesson(), name=" \r\n "))


def test_a_name_cannot_add_a_property_to_the_calendar() -> None:
    data = render(lesson(), name="Lucía\r\nX-INJECTED:1")
    assert not any(line.startswith("X-INJECTED") for line in unfolded(data))
    assert "X-WR-CALNAME:Lucía X-INJECTED:1" in unfolded(data)


def test_a_title_cannot_add_an_event_or_a_property() -> None:
    hostile = (
        "Math\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nSUMMARY:pwned\r\nATTENDEE:mailto:x@example.test"
    )
    data = render(lesson(title=hostile))
    event = only_event(data)
    assert str(event["SUMMARY"]) == plain(hostile)
    assert "ATTENDEE" not in event
    assert unfolded(data).count("BEGIN:VEVENT") == 1


def test_a_label_cannot_add_a_property() -> None:
    data = render(lesson(), label="Lucía\r\nX-EVIL:1")
    assert not any(line.startswith("X-EVIL") for line in unfolded(data))


def test_a_label_is_cleaned_like_a_title() -> None:
    event = only_event(render(lesson(title="Inglés"), label="Lu\r\ncía\u202e"))
    assert str(event["SUMMARY"]) == "Lu cía: Inglés"


def test_a_teacher_cannot_add_a_property() -> None:
    data = render(lesson(teacher="Ana\r\nATTENDEE:mailto:x@example.test"))
    assert "ATTENDEE" not in only_event(data)


def test_the_file_of_a_title_with_a_lone_surrogate_is_still_made() -> None:
    assert str(only_event(render(lesson(title="a\ud800b")))["SUMMARY"]) == "ab"


def test_long_lines_fold_at_75_octets_and_unfold_to_the_same_words() -> None:
    title = "ñ" * 200 + " 😀" * 40
    data = render(lesson(title=title))
    assert all(len(line) <= 75 for line in data.split(b"\r\n"))
    assert str(only_event(data)["SUMMARY"]) == title


def test_the_entries_are_ordered_by_start_whatever_order_they_arrive_in() -> None:
    events = (lesson(date(2026, 1, 14)), lesson(date(2026, 1, 12)), lesson(date(2026, 1, 13)))
    forwards = render(*events)
    backwards = render(*reversed(events))
    assert forwards == backwards
    starts = [event.decoded("DTSTART") for event in vevents(forwards)]
    assert starts == sorted(starts)


def test_entries_that_start_together_with_the_same_id_are_ordered_by_scope() -> None:
    together = lesson()
    entries = [CalendarEntry(together, "mateo", "Mateo"), CalendarEntry(together, "lucia", "Lucía")]
    forwards = render_calendar("Both", entries, zone=MADRID, stamped_at=STAMP)
    backwards = render_calendar("Both", entries[::-1], zone=MADRID, stamped_at=STAMP)
    assert forwards == backwards
    assert [str(event["UID"]) for event in vevents(forwards)] == [
        "lucia.lesson-1|2026-01-12@alexia-familia-api",
        "mateo.lesson-1|2026-01-12@alexia-familia-api",
    ]


def test_a_calendar_with_no_entries_is_still_a_calendar() -> None:
    data = render()
    assert vevents(data) == []
    assert unfolded(data)[0] == "BEGIN:VCALENDAR"


def test_every_entry_survives_a_round_trip_through_a_reader() -> None:
    events = (
        lesson(date(2026, 1, 12)),
        occasion("Entrevista: Aceptada"),
        all_day(first=date(2026, 1, 15), last=date(2026, 1, 16), kind="school_event"),
    )
    read = vevents(render(*events, label="Lucía"))
    assert [str(event["SUMMARY"]) for event in read] == [
        "Lucía: Matemáticas",
        "Lucía: Entrevista: Aceptada",
        "Lucía: FESTIVO",
    ]
    assert read[0].decoded("DTSTART") == events[0].starts_at
    assert read[1].decoded("DTEND") == events[1].ends_at
    assert read[2].decoded("DTEND") == date(2026, 1, 17)


@given(ANY_TEXT)
def test_whatever_a_title_says_the_file_holds_one_entry_with_the_same_plain_words(
    title: str,
) -> None:
    data = render(lesson(title=title))
    assert str(only_event(data)["SUMMARY"]) == plain(title)


@given(ANY_TEXT)
def test_whatever_a_teacher_is_called_the_description_is_that_name_in_plain_words(
    teacher: str,
) -> None:
    event = only_event(render(lesson(teacher=teacher)))
    shown = plain(teacher)
    if shown:
        assert str(event["DESCRIPTION"]) == f"Teacher {shown}."
    else:
        assert "DESCRIPTION" not in event


@pytest.mark.parametrize(
    ("text", "written"),
    [
        ("\\N", "\\\\N"),
        ("Teacher \\N.", "Teacher \\\\N."),
        ("a\\nb", "a\\\\nb"),
        ("semi;colon, comma", "semi\\;colon\\, comma"),
        ("ends with a backslash \\", "ends with a backslash \\\\"),
    ],
)
def test_a_name_is_written_with_the_escapes_of_the_standard_and_reads_back_as_it_was(
    text: str, written: str
) -> None:
    data = render(lesson(title=text, teacher=text), name=text)

    lines = unfolded(data)
    assert f"X-WR-CALNAME:{written}" in lines
    assert f"SUMMARY:{written}" in lines
    assert f"DESCRIPTION:Teacher {written}." in lines
    event = only_event(data)
    assert str(event["SUMMARY"]) == text
    assert str(event["DESCRIPTION"]) == f"Teacher {text}."


def test_a_description_of_two_sentences_keeps_its_line_break_as_an_escape() -> None:
    signals = LessonSignals(tasks=1, activities=0, notes=0, tests=0, substitution=False)

    data = render(lesson(signals=signals))

    assert "DESCRIPTION:Teacher Ana Muestra.\\nThe school flagged 1 task." in unfolded(data)
    assert str(only_event(data)["DESCRIPTION"]) == (
        "Teacher Ana Muestra.\nThe school flagged 1 task."
    )


def test_an_id_with_a_backslash_is_written_with_the_escapes_of_the_standard() -> None:
    data = render(lesson(event_id="a\\Nb"))

    assert "UID:kid.a\\\\Nb|2026-01-12@alexia-familia-api" in unfolded(data)
    assert str(only_event(data)["UID"]) == "kid.a\\Nb|2026-01-12@alexia-familia-api"


ALLOWED_NAMES = frozenset(
    {
        "BEGIN",
        "END",
        "VERSION",
        "PRODID",
        "CALSCALE",
        "METHOD",
        "X-WR-CALNAME",
        "X-WR-TIMEZONE",
        "REFRESH-INTERVAL;VALUE=DURATION",
        "X-PUBLISHED-TTL",
        "UID",
        "DTSTAMP",
        "SUMMARY",
        "DTSTART",
        "DTEND",
        "DESCRIPTION",
    }
)


@given(ANY_TEXT, ANY_TEXT)
def test_whatever_a_name_and_a_label_say_the_file_keeps_its_shape(name: str, label: str) -> None:
    data = render(lesson(), name=name, label=label)
    names = {line.split(":", 1)[0] for line in unfolded(data) if line}
    assert names <= ALLOWED_NAMES
    assert len(vevents(data)) == 1


@given(st.text(alphabet=st.characters(exclude_categories=["Cs"]), max_size=200))
def test_whatever_an_id_says_its_uid_is_one_line_without_spaces(identifier: str) -> None:
    entry = CalendarEntry(lesson(event_id=identifier), scope="kid", label=None)
    data = render_calendar("X", [entry], zone=MADRID, stamped_at=STAMP)
    uid = str(only_event(data)["UID"])
    assert uid.isprintable()
    assert " " not in uid
    assert uid.endswith("@alexia-familia-api")
