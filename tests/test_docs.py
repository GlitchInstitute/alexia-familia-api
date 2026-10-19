"""Every link in the docs leads to a page that exists, and every example is an answer of the API."""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from gen_docs import anchor_of
from tests.openapi_reply import DOCUMENT, complaints_about

ROOT = Path(__file__).resolve().parent.parent
FENCE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[ \t]*$", re.MULTILINE | re.DOTALL)
JSON_EXAMPLE = re.compile(r"^```json\n(.*?)^```", re.MULTILINE | re.DOTALL)
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)


def markdown_files() -> list[Path]:
    names = ("README.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md")
    found = [ROOT / name for name in names]
    found += sorted((ROOT / "docs").glob("*.md"))
    found += sorted((ROOT / ".github").glob("*.md"))
    return [path for path in found if path.exists()]


def prose_of(path: Path) -> str:
    """The text of a Markdown file without its code blocks, where `[a](b)` is not a link."""
    return FENCE.sub("", path.read_text(encoding="utf-8"))


def anchors_of(path: Path) -> set[str]:
    """The ids that GitHub gives the headings of a file, with `-1` and `-2` for repeats."""
    seen: Counter[str] = Counter()
    anchors: set[str] = set()
    for heading in HEADING.findall(prose_of(path)):
        anchor = anchor_of(re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading))
        anchors.add(anchor if seen[anchor] == 0 else f"{anchor}-{seen[anchor]}")
        seen[anchor] += 1
    return anchors


def broken_links(path: Path, root: Path) -> list[str]:
    problems = []
    name_of = path.relative_to(root)
    for target in LINK.findall(prose_of(path)):
        if re.match(r"[a-z][a-z0-9+.-]*:", target):
            continue
        name, _, fragment = target.partition("#")
        destination = (path.parent / name).resolve() if name else path
        if not destination.exists():
            problems.append(f"{name_of} links to {target}, which does not exist")
        elif fragment and destination.suffix == ".md" and fragment not in anchors_of(destination):
            problems.append(f"{name_of} links to {target}, which has no such heading")
    return problems


def reply_schemas() -> list[dict[str, Any]]:
    """The models that the routes of the document answer with, for a success and for a refusal."""
    schemas: list[dict[str, Any]] = []
    for item in DOCUMENT["paths"].values():
        for operation in item.values():
            for answer in operation["responses"].values():
                for content in answer.get("content", {}).values():
                    schema = content.get("schema", {})
                    if "$ref" in schema and schema not in schemas:
                        schemas.append(schema)
    return schemas


def stale_examples(path: Path, root: Path) -> list[str]:
    """The json examples of a page that no answer of the API accepts, each with its line."""
    problems = []
    text = path.read_text(encoding="utf-8")
    for match in JSON_EXAMPLE.finditer(text):
        body = json.loads(match[1])
        nearest = min((complaints_about(body, schema) for schema in reply_schemas()), key=len)
        if nearest:
            line = text.count("\n", 0, match.start()) + 1
            problems.append(
                f"{path.relative_to(root)}:{line} has a json example that no answer of the API "
                f"accepts. The closest answer reports {nearest[0]}"
            )
    return problems


def test_the_scanner_finds_a_missing_page_and_a_missing_heading(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    page = tmp_path / "docs" / "a.md"
    page.write_text(
        "# Title\n\n## Part two\n\n```\n[not a link](nowhere.md)\n```\n", encoding="utf-8"
    )
    other = tmp_path / "docs" / "b.md"
    other.write_text(
        "[ok](a.md#part-two) [gone](c.md) [bad](a.md#part-three) [web](https://example.test/x) "
        "[mail](mailto:a@example.test) [here](#top)\n\n# Top\n",
        encoding="utf-8",
    )

    assert broken_links(other, tmp_path) == [
        "docs/b.md links to c.md, which does not exist",
        "docs/b.md links to a.md#part-three, which has no such heading",
    ]


def test_a_repeated_heading_gets_the_numbered_link_that_github_gives_it(tmp_path: Path) -> None:
    page = tmp_path / "a.md"
    page.write_text("# One\n\n## Same\n\n## Same\n\n[again](#same-1) [none](#same-2)\n", "utf-8")

    assert broken_links(page, tmp_path) == ["a.md links to #same-2, which has no such heading"]


def test_every_link_in_the_docs_leads_to_a_page_and_a_heading_that_exist() -> None:
    problems = [problem for path in markdown_files() for problem in broken_links(path, ROOT)]

    assert problems == []


def test_a_json_example_that_no_answer_accepts_is_reported_with_its_line(tmp_path: Path) -> None:
    page = tmp_path / "a.md"
    page.write_text(
        '# A\n\n```json\n{"items": [{"id": 1}]}\n```\n\n```jsonl\n{"level": "INFO"}\n```\n',
        encoding="utf-8",
    )

    problems = stale_examples(page, tmp_path)

    assert len(problems) == 1
    assert problems[0].startswith("a.md:3 has a json example that no answer of the API accepts.")


def test_a_json_example_that_an_answer_accepts_passes(tmp_path: Path) -> None:
    page = tmp_path / "a.md"
    page.write_text('```json\n{"items": []}\n```\n', encoding="utf-8")

    assert stale_examples(page, tmp_path) == []


def test_every_json_example_in_the_docs_is_an_answer_that_the_api_accepts() -> None:
    problems = [problem for path in markdown_files() for problem in stale_examples(path, ROOT)]

    assert problems == []
