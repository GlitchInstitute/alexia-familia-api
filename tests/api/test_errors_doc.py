"""The errors page lists every code the server sends, with the status each one carries.

A person writes the page, so this test keeps it true in both directions. A code the server can
send must be on the page with its status, and a code or status on the page must be one the server
can send. The codes come from four places. The portal failures come from the table the problem
tests already hold. The refusals the API decides on come from the `ApiError(status, "code", ...)`
calls in the source. The lookups that find nothing come from the kinds a lookup can fail on. The
answers built from constants or by the framework are listed below, and other tests send each of
them.
"""

import ast
import re
from collections import defaultdict
from pathlib import Path
from typing import get_args

import pytest

from alexia_api.services.errors import NotFoundKind
from tests.api.test_problems import EXPECTED_STATUS

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "errors.md"
SOURCE = ROOT / "src" / "alexia_api"
ROW = re.compile(r"^\| `(?P<code>[a-z_]+)` \| (?P<statuses>\d{3}(?: or \d{3})*) \|", re.MULTILINE)

FIXED_ANSWERS: frozenset[tuple[str, int]] = frozenset(
    {
        ("invalid_host", 400),
        ("not_found", 404),
        ("method_not_allowed", 405),
        ("payload_too_large", 413),
        ("validation_error", 422),
        ("internal_error", 500),
    }
)


def on_the_page() -> dict[str, set[int]]:
    statuses: defaultdict[str, set[int]] = defaultdict(set)
    for row in ROW.finditer(PAGE.read_text(encoding="utf-8")):
        statuses[row["code"]] |= {int(number) for number in re.findall(r"\d{3}", row["statuses"])}
    return dict(statuses)


def refusals_in_the_source() -> set[tuple[str, int]]:
    found: set[tuple[str, int]] = set()
    for path in sorted(SOURCE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ApiError"
            ):
                continue
            status, code = node.args[:2]
            if not (
                isinstance(status, ast.Constant)
                and isinstance(status.value, int)
                and isinstance(code, ast.Constant)
                and isinstance(code.value, str)
            ):
                pytest.fail(
                    f"{path.relative_to(ROOT)}:{node.lineno} builds an ApiError that this test "
                    "cannot read, so give it a number and a text as its first two arguments"
                )
            found.add((code.value, status.value))
    return found


def what_the_server_sends() -> set[tuple[str, int]]:
    from_the_portal = {(detail.code, status) for detail, status in EXPECTED_STATUS}
    nothing_found = {(f"{kind}_not_found", 404) for kind in get_args(NotFoundKind)}
    return refusals_in_the_source() | from_the_portal | nothing_found | set(FIXED_ANSWERS)


def test_the_scan_finds_the_refusals_the_api_decides_on() -> None:
    assert {"missing_api_key", "invalid_window", "rate_limited"} <= {
        code for code, _ in refusals_in_the_source()
    }


def test_the_page_lists_every_code_the_server_sends_with_its_status() -> None:
    page = on_the_page()

    missing = sorted(
        f"{code} {status}"
        for code, status in what_the_server_sends()
        if status not in page.get(code, set())
    )

    assert not missing, f"docs/errors.md does not list {missing}"


def test_the_page_lists_no_code_or_status_the_server_does_not_send() -> None:
    sent = what_the_server_sends()

    stale = sorted(
        f"{code} {status}"
        for code, statuses in on_the_page().items()
        for status in statuses
        if (code, status) not in sent
    )

    assert not stale, f"docs/errors.md lists answers the server never sends, {stale}"
