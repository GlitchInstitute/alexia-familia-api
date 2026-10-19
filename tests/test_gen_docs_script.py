"""The script that writes the pages from the code, and the check that the pages are current."""

from pathlib import Path
from typing import Any

import pytest

from gen_docs import (
    REFRESH_COMMAND,
    DocumentError,
    anchor_of,
    describe_type,
    main,
    render_endpoints,
    render_operation,
)

REF = "#/components/schemas/"


@pytest.mark.parametrize(
    ("heading", "anchor"),
    [
        ("List the messages in a folder", "list-the-messages-in-a-folder"),
        ("The `cache` table", "the-cache-table"),
        ("AgendaEvent", "agendaevent"),
        ("Show one child's data", "show-one-childs-data"),
        ("Año nuevo", "año-nuevo"),
        ("snake_case stays", "snake_case-stays"),
    ],
)
def test_an_anchor_is_the_id_that_github_gives_a_heading(heading: str, anchor: str) -> None:
    assert anchor_of(heading) == anchor


@pytest.mark.parametrize(
    ("schema", "words"),
    [
        ({"type": "string"}, "text"),
        ({"type": "string", "format": "date"}, "date, written `YYYY-MM-DD`"),
        ({"type": "string", "format": "date-time"}, "date and time with an offset"),
        ({"type": "boolean"}, "true or false"),
        ({"type": "number"}, "number"),
        ({"type": "integer"}, "whole number"),
        (
            {"type": "integer", "minimum": 1, "maximum": 100},
            "whole number, at least 1 and at most 100",
        ),
        ({"type": "integer", "minimum": 0.0}, "whole number, at least 0"),
        ({"type": "integer", "exclusiveMinimum": 0}, "whole number, more than 0"),
        ({"enum": ["a", "b"]}, 'one of `"a"`, `"b"`'),
        ({"enum": [1, 2]}, "one of `1`, `2`"),
        ({"const": "ok"}, '`"ok"`'),
        ({"$ref": f"{REF}Child"}, "[Child](#child)"),
        ({"type": "array", "items": {"$ref": f"{REF}Child"}}, "list of [Child](#child)"),
        ({"type": "array", "items": {"type": "string"}}, "list of text"),
        ({"type": "object", "additionalProperties": {"type": "integer"}}, "table of whole number"),
        ({"type": "object"}, "object"),
        ({"type": "null"}, "null"),
        ({}, "any value"),
        ({"anyOf": [{"type": "integer"}, {"type": "null"}]}, "whole number or null"),
        ({"anyOf": [{"type": "string"}, {"type": "integer"}]}, "one of text, whole number"),
        ({"anyOf": [{"$ref": f"{REF}Child"}, {"type": "null"}]}, "[Child](#child) or null"),
        (
            {
                "oneOf": [{"$ref": f"{REF}Open"}, {"$ref": f"{REF}Shut"}],
                "discriminator": {"propertyName": "state"},
            },
            "one of [Open](#open), [Shut](#shut), told apart by `state`",
        ),
    ],
)
def test_a_schema_is_described_in_plain_words(schema: dict[str, Any], words: str) -> None:
    assert describe_type(schema) == words


SCHEMES: dict[str, Any] = {
    "BearerKey": {"type": "http", "scheme": "bearer"},
    "HeaderKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
    "FeedKey": {"type": "apiKey", "in": "query", "name": "key"},
}


def operation(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "summary": "List the messages",
        "description": "Needs the `read` scope.",
        "security": [{"BearerKey": []}, {"HeaderKey": []}],
        "parameters": [
            {
                "name": "account",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
                "description": "The account.",
            },
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer", "default": 25},
                "description": "How many.",
            },
            {
                "name": "folder",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
            },
        ],
        "responses": {
            "200": {
                "description": "Successful Response",
                "content": {"application/json": {"schema": {"$ref": f"{REF}Page"}}},
                "headers": {"Age": {"description": "How old the answer is.", "schema": {}}},
            },
            "404": {"description": "Not Found"},
            "401": {"description": "Unauthorized"},
        },
    }
    return {**base, **changes}


def rendered(changed: dict[str, Any], method: str = "get", path: str = "/x") -> str:
    return "\n".join(render_operation(method, path, changed, SCHEMES))


def test_a_route_says_how_to_send_a_key_what_it_takes_and_what_it_answers() -> None:
    text = rendered(operation(), path="/v1/accounts/{account}/messages")

    assert text.startswith("### List the messages\n\n`GET /v1/accounts/{account}/messages`\n")
    assert "Needs the `read` scope." in text
    assert "**Key.** Send one as `Authorization: Bearer <key>` or `X-API-Key: <key>`." in text
    assert "| `account` | text | The account. |" in text
    assert "| `limit` | whole number | `25` | How many. |" in text
    assert "| `folder` | text | required |  |" in text
    assert "- `200` returns [Page](#page) as `application/json`." in text
    assert "| `Age` | How old the answer is. |" in text
    assert "A failure answers `401` or `404` with a [Problem](#problem)" in text


def test_a_route_with_three_ways_to_send_a_key_lists_them_all() -> None:
    changed = operation(security=[{"BearerKey": []}, {"HeaderKey": []}, {"FeedKey": []}])

    text = rendered(changed)

    assert "Send one as `Authorization: Bearer <key>`, `X-API-Key: <key>`, or `?key=<key>`." in text


def test_a_route_without_security_says_that_it_is_open() -> None:
    text = rendered(operation(security=[]), path="/healthz")

    assert "**Key.** None. This route is open to anyone who can reach the server." in text


def test_a_file_answer_names_its_media_type_and_ends_each_note_with_one_full_stop() -> None:
    changed = operation(
        responses={
            "200": {
                "description": "The file itself.",
                "content": {"*/*": {"schema": {"type": "string"}}},
            },
            "204": {"description": "Nothing to say"},
        }
    )

    text = rendered(changed)

    assert "- `200` returns a file as `*/*`. The file itself.\n" in text
    assert "- `204` returns nothing. Nothing to say.\n" in text


def test_a_request_body_is_listed_with_its_media_type() -> None:
    changed = operation(
        requestBody={
            "required": True,
            "description": "What to send.",
            "content": {"application/json": {"schema": {"$ref": f"{REF}Draft"}}},
        }
    )

    text = rendered(changed, method="post")

    assert "**Request body**\n\nWhat to send.\n\n" in text
    assert "- Required. `application/json`, [Draft](#draft)." in text


def test_a_security_scheme_with_no_words_is_refused() -> None:
    schemes = {"BearerKey": {"type": "oauth2"}, "HeaderKey": {}}

    with pytest.raises(DocumentError, match="no words for the security scheme"):
        render_operation("get", "/x", operation(), schemes)


def test_a_route_without_a_summary_is_refused() -> None:
    with pytest.raises(DocumentError, match="has no summary"):
        render_operation("get", "/x", operation(summary=""), SCHEMES)


def spec_of(*summaries: str) -> dict[str, Any]:
    paths = {
        f"/route-{number}": {"get": operation(summary=summary, tags=["one"], security=[])}
        for number, summary in enumerate(summaries)
    }
    return {
        "info": {"description": "About the server.\n\n"},
        "tags": [{"name": "one", "description": "The first group."}],
        "paths": paths,
        "components": {
            "schemas": {
                "Page": {
                    "description": "One page.",
                    "properties": {
                        "total": {"type": "integer", "description": "How many."},
                        "next": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    },
                    "required": ["total"],
                }
            }
        },
    }


def test_the_page_lists_each_route_in_a_table_and_each_model_as_a_table_of_fields() -> None:
    text = render_endpoints(spec_of("Show a page", "Show another page"))

    assert "About the server.\n\nEvery route lives at the address of your server" in text
    assert "| GET | `/route-0` | [Show a page](#show-a-page) |" in text
    assert "## Routes for one\n\nThe first group." in text
    assert "### Show another page\n\n`GET /route-1`" in text
    assert "| `total` | whole number | How many. |" in text
    assert "| `next` | whole number or null, optional |  |" in text
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


def test_two_routes_that_share_a_title_are_refused_because_their_links_would_collide() -> None:
    with pytest.raises(DocumentError, match="share the link #show-a-page"):
        render_endpoints(spec_of("Show a page", "Show a page"))


def test_the_pages_are_written_and_then_found_current(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "wrote docs/openapi.json",
        "wrote docs/endpoints.md",
        "wrote docs/settings.md",
    ]

    assert main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "the pages are current\n"
    assert main(["--root", str(tmp_path), "--check"]) == 0
    assert capsys.readouterr().out == "gen_docs ok pages=3\n"


def test_a_check_names_each_stale_page_and_the_command_that_fixes_it_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--root", str(tmp_path)])
    capsys.readouterr()
    settings = tmp_path / "docs" / "settings.md"
    settings.write_text("edited by hand\n", encoding="utf-8")
    (tmp_path / "docs" / "openapi.json").unlink()

    assert main(["--root", str(tmp_path), "--check"]) == 1

    assert capsys.readouterr().err.splitlines() == [
        f"gen_docs: docs/openapi.json is out of date, run `{REFRESH_COMMAND}`",
        f"gen_docs: docs/settings.md is out of date, run `{REFRESH_COMMAND}`",
    ]
    assert settings.read_text(encoding="utf-8") == "edited by hand\n"
    assert not (tmp_path / "docs" / "openapi.json").exists()


def test_the_pages_in_the_repository_are_current(capsys: pytest.CaptureFixture[str]) -> None:
    status = main(["--check"])

    assert status == 0, capsys.readouterr().err
