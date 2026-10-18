"""Findings are shown in columns, with the fix under the message and one closing sentence."""

import pytest
from click import unstyle

from alexia_api.cli.report import render, verdict
from alexia_api.doctor import Finding, Level


def finding(level: Level) -> Finding:
    return Finding(level, "subject", "message")


def test_each_finding_is_a_line_with_its_level_subject_and_message_in_columns() -> None:
    findings = [
        Finding("ok", "config", "read alexia-api.toml"),
        Finding(
            "fail",
            "accounts.marta",
            "the portal address is still the example portal.example.test",
            "paste the address into login_url",
        ),
    ]

    assert unstyle(render(findings)).splitlines() == [
        "ok    config" + " " * 10 + "read alexia-api.toml",
        "fail  accounts.marta  the portal address is still the example portal.example.test",
        " " * 22 + "Fix: paste the address into login_url",
    ]


def test_a_message_over_several_lines_keeps_the_later_lines_under_the_first() -> None:
    message = "the configuration has problems\n  login_url: must start with https://"

    shown = unstyle(render([Finding("stop", "config", message, "fix it")]))

    assert shown.splitlines() == [
        "stop  config  the configuration has problems",
        " " * 14 + "  login_url: must start with https://",
        " " * 14 + "Fix: fix it",
    ]


def test_a_finding_without_a_message_leaves_no_trailing_space() -> None:
    assert unstyle(render([Finding("ok", "keys", "")])) == "ok    keys"


def test_no_findings_make_no_lines() -> None:
    assert render([]) == ""


@pytest.mark.parametrize(
    ("level", "code"),
    [("ok", 32), ("warn", 33), ("fail", 31), ("stop", 31)],
)
def test_the_level_is_colored_for_a_terminal(level: Level, code: int) -> None:
    assert render([finding(level)]).startswith(f"\x1b[{code}m")


@pytest.mark.parametrize(
    ("levels", "sentence"),
    [
        ([], "Everything checks out."),
        (["ok"], "Everything checks out."),
        (["ok", "warn"], "Nothing is broken, but read the lines marked warn."),
        (["warn", "fail"], "The server can start, but the lines marked fail need attention."),
        (
            ["fail", "warn", "stop"],
            "The server cannot start. Fix the lines marked stop and run this again.",
        ),
    ],
)
def test_the_closing_sentence_follows_the_worst_level(levels: list[Level], sentence: str) -> None:
    assert verdict([finding(level) for level in levels]) == sentence
