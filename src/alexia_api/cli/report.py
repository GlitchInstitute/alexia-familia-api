"""How the doctor's findings are shown to a person."""

from collections.abc import Sequence
from typing import Final

import typer

from alexia_api.doctor import Finding, Level

COLORS: Final[dict[Level, str]] = {"ok": "green", "warn": "yellow", "fail": "red", "stop": "red"}
LABEL_WIDTH: Final = 4
GAP: Final = "  "


def render(findings: Sequence[Finding]) -> str:
    """One line for each finding, lined up in columns, with the fix on the line below it.

    A message that runs over several lines keeps its later lines under the first one. The level
    is colored when the output is a terminal. A pipe or a file gets plain text.
    """
    subject_width = max((len(finding.subject) for finding in findings), default=0)
    indent = " " * (LABEL_WIDTH + len(GAP) + subject_width + len(GAP))
    lines: list[str] = []
    for finding in findings:
        label = typer.style(finding.level.ljust(LABEL_WIDTH), fg=COLORS[finding.level])
        first, *rest = finding.message.splitlines() or [""]
        lines.append(f"{label}{GAP}{finding.subject.ljust(subject_width)}{GAP}{first}")
        lines.extend(f"{indent}{line}" for line in rest)
        if finding.fix is not None:
            lines.append(f"{indent}Fix: {finding.fix}")
    return "\n".join(line.rstrip() for line in lines)


def verdict(findings: Sequence[Finding]) -> str:
    """The one sentence a person needs after reading the lines."""
    levels = {finding.level for finding in findings}
    if "stop" in levels:
        return "The server cannot start. Fix the lines marked stop and run this again."
    if "fail" in levels:
        return "The server can start, but the lines marked fail need attention."
    if "warn" in levels:
        return "Nothing is broken, but read the lines marked warn."
    return "Everything checks out."
