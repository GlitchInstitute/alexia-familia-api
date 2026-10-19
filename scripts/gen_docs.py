#!/usr/bin/env python3
"""Write the pages that come from the code, or check that they are current.

    python scripts/gen_docs.py           write the pages
    python scripts/gen_docs.py --check   fail when a page differs from what the code produces

The pages are `docs/openapi.json`, `docs/endpoints.md`, and `docs/settings.md`. The first two come
from the OpenAPI document of the REST API, and the third from the models in `config.py`. A test
runs the check, so a route or a setting cannot change without its page changing in the same commit.
"""

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from alexia_api.api.app import openapi_document
from alexia_api.reference import Section, SettingDoc, catalog, format_value

type Schema = Mapping[str, Any]

ROOT: Final = Path(__file__).resolve().parents[1]
REFRESH_COMMAND: Final = "pixi run -e dev docs"
NOTICE: Final = (
    "This page comes from the code, so do not edit it by hand. "
    f"Run `{REFRESH_COMMAND}` to write it again."
)
HTTP_METHODS: Final = ("get", "put", "post", "patch", "delete", "head", "options")
PLAIN_SUCCESS: Final = "Successful Response"
ERROR_STATUS: Final = 400
NULL: Final[Schema] = {"type": "null"}
STRING_FORMATS: Final = {
    "date": "date, written `YYYY-MM-DD`",
    "date-time": "date and time with an offset",
}
OPEN_ROUTE: Final = "None. This route is open to anyone who can reach the server."
ENDPOINTS_INTRO: Final = (
    "Every route lives at the address of your server, for example `http://127.0.0.1:8000`. "
    "The [API guide](api-guide.md) explains what all routes share, such as ids, times, "
    "paging, and the headers that tell you how fresh an answer is."
)
SETTINGS_INTRO: Final = (
    "Put a setting in `alexia-api.toml`, or set it with an environment variable. A variable "
    "wins over the file. The [configuration guide](configuration.md) explains both ways, "
    "how to keep passwords out of the file, and how to set up several accounts."
)


class DocumentError(Exception):
    """The OpenAPI document or the settings cannot be turned into a page."""


def anchor_of(heading: str) -> str:
    """The id that GitHub gives a heading, so a link can point at it."""
    lowered = heading.strip().lower()
    return re.sub(r"[^\w\- ]", "", lowered).replace(" ", "-")


def _cell(text: object) -> str:
    return str(text).strip().replace("\n", " ").replace("|", "\\|")


def _table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows)
    return lines


def _literal(value: object) -> str:
    return f"`{json.dumps(value, ensure_ascii=False)}`"


def _plain_number(value: object) -> str:
    """Write 0.0 as 0, because JSON Schema keeps a float where a whole number is meant."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _bounded(kind: str, schema: Schema) -> str:
    phrases = [
        f"{label} {_plain_number(schema[name])}"
        for name, label in (
            ("minimum", "at least"),
            ("exclusiveMinimum", "more than"),
            ("maximum", "at most"),
            ("exclusiveMaximum", "less than"),
        )
        if name in schema
    ]
    return kind + (", " + " and ".join(phrases) if phrases else "")


def _choice(options: Sequence[Schema], discriminator: Schema | None) -> str:
    present = [option for option in options if option != NULL]
    parts = [describe_type(option) for option in present]
    text = parts[0] if len(parts) == 1 else "one of " + ", ".join(parts)
    if discriminator is not None and len(parts) > 1:
        text += f", told apart by `{discriminator['propertyName']}`"
    return text + (" or null" if len(present) != len(options) else "")


def describe_type(schema: Schema) -> str:
    """Say what a value is, in plain words, with a link to any model it names."""
    if "$ref" in schema:
        name = str(schema["$ref"]).rsplit("/", 1)[-1]
        return f"[{name}](#{anchor_of(name)})"
    for key in ("oneOf", "anyOf"):
        if key in schema:
            return _choice(schema[key], schema.get("discriminator"))
    if "const" in schema:
        return _literal(schema["const"])
    if "enum" in schema:
        return "one of " + ", ".join(_literal(value) for value in schema["enum"])
    match schema.get("type"):
        case "array":
            return f"list of {describe_type(schema.get('items', {}))}"
        case "object":
            extra = schema.get("additionalProperties")
            return f"table of {describe_type(extra)}" if isinstance(extra, Mapping) else "object"
        case "string":
            return STRING_FORMATS.get(str(schema.get("format", "")), "text")
        case "integer":
            return _bounded("whole number", schema)
        case "number":
            return _bounded("number", schema)
        case "boolean":
            return "true or false"
        case "null":
            return "null"
        case _:
            return "any value"


def _words_of(schema: Schema) -> str:
    return str(schema.get("description", ""))


def _join_or(items: Sequence[str]) -> str:
    if len(items) < 3:
        return " or ".join(items)
    return ", ".join(items[:-1]) + f", or {items[-1]}"


def _way_to_send(scheme: Schema) -> str:
    match scheme:
        case {"type": "http", "scheme": "bearer"}:
            return "`Authorization: Bearer <key>`"
        case {"type": "apiKey", "in": "header", "name": name}:
            return f"`{name}: <key>`"
        case {"type": "apiKey", "in": "query", "name": name}:
            return f"`?{name}=<key>`"
        case _:
            raise DocumentError(f"no words for the security scheme {dict(scheme)!r}")


def _access_line(operation: Schema, schemes: Schema) -> str:
    requirements: Sequence[Mapping[str, Any]] = operation.get("security", [])
    if not requirements:
        return f"**Key.** {OPEN_ROUTE}"
    ways = [_way_to_send(schemes[name]) for requirement in requirements for name in requirement]
    return f"**Key.** Send one as {_join_or(ways)}."


def _meaning_of(parameter: Schema) -> str:
    return str(parameter.get("description") or _words_of(parameter["schema"]))


def _default_column(parameter: Schema) -> str:
    if parameter.get("required"):
        return "required"
    if "default" in parameter["schema"]:
        return _literal(parameter["schema"]["default"])
    return "none"


def _path_parameter_table(parameters: Sequence[Schema]) -> list[str]:
    rows = (
        (f"`{item['name']}`", describe_type(item["schema"]), _meaning_of(item))
        for item in parameters
    )
    return _table(["Name", "Kind", "What it is"], rows)


def _query_parameter_table(parameters: Sequence[Schema]) -> list[str]:
    rows = (
        (
            f"`{item['name']}`",
            describe_type(item["schema"]),
            _default_column(item),
            _meaning_of(item),
        )
        for item in parameters
    )
    return _table(["Name", "Kind", "Default", "What it does"], rows)


def _body_lines(body: Schema | None) -> list[str]:
    if body is None:
        return []
    needed = "Required" if body.get("required") else "Optional"
    lines = ["**Request body**", ""]
    if body.get("description"):
        lines += [str(body["description"]).strip(), ""]
    for media, content in body.get("content", {}).items():
        lines.append(f"- {needed}. `{media}`, {describe_type(content.get('schema', {}))}.")
    return [*lines, ""]


def _is_problem(status: str) -> bool:
    return status.isdigit() and int(status) >= ERROR_STATUS


def _body_words(media: str, schema: Schema) -> str:
    if schema.get("type") == "string" and "json" not in media:
        return "a file"
    return describe_type(schema)


def _sentence(text: str) -> str:
    return text if text.endswith(".") else text + "."


def _answer_lines(status: str, response: Schema) -> list[str]:
    noted = _words_of(response)
    note = "" if noted in {"", PLAIN_SUCCESS} else " " + _sentence(noted)
    content = response.get("content", {})
    if not content:
        return [f"- `{status}` returns nothing.{note}"]
    return [
        f"- `{status}` returns {_body_words(media, body.get('schema', {}))} as `{media}`.{note}"
        for media, body in content.items()
    ]


def _header_lines(status: str, headers: Schema) -> list[str]:
    rows = ((f"`{name}`", _words_of(item)) for name, item in headers.items())
    intro = f"The `{status}` answer carries these headers."
    return ["", intro, "", *_table(["Header", "What it says"], rows)]


def _response_lines(responses: Mapping[str, Schema]) -> list[str]:
    answers = {status: item for status, item in responses.items() if not _is_problem(status)}
    problems = [f"`{status}`" for status in sorted(filter(_is_problem, responses), key=int)]
    lines = ["**Answers**", ""]
    for status, response in answers.items():
        lines += _answer_lines(status, response)
    for status, response in answers.items():
        if response.get("headers"):
            lines += _header_lines(status, response["headers"])
    if problems:
        failure = (
            f"A failure answers {_join_or(problems)} with a [Problem](#problem) as "
            "`application/problem+json`. The [errors page](errors.md) lists every `code`."
        )
        lines += ["", failure]
    return [*lines, ""]


def _operations(spec: Schema) -> list[tuple[str, str, Schema]]:
    return [
        (method, path, item[method])
        for path, item in spec["paths"].items()
        for method in HTTP_METHODS
        if method in item
    ]


def _title_of(operation: Schema) -> str:
    title = operation.get("summary")
    if not isinstance(title, str) or not title:
        raise DocumentError(f"the route {operation.get('operationId')} has no summary")
    return title


def render_operation(method: str, path: str, operation: Schema, schemes: Schema) -> list[str]:
    """One route, with what it needs, what it takes, and what it answers."""
    parameters = operation.get("parameters", [])
    in_path = [item for item in parameters if item["in"] == "path"]
    in_query = [item for item in parameters if item["in"] == "query"]
    lines = [f"### {_title_of(operation)}", "", f"`{method.upper()} {path}`", ""]
    if operation.get("description"):
        lines += [str(operation["description"]).strip(), ""]
    lines += [_access_line(operation, schemes), ""]
    if in_path:
        lines += ["**Path parameters**", "", *_path_parameter_table(in_path), ""]
    if in_query:
        lines += ["**Query parameters**", "", *_query_parameter_table(in_query), ""]
    lines += _body_lines(operation.get("requestBody"))
    lines += _response_lines(operation.get("responses", {}))
    return lines


def render_schema(name: str, schema: Schema) -> list[str]:
    """One model, as a table of its fields."""
    lines = [f"### {name}", ""]
    if schema.get("description"):
        lines += [str(schema["description"]).strip(), ""]
    properties: Mapping[str, Schema] = schema.get("properties", {})
    if not properties:
        return [*lines, f"A value of kind {describe_type(schema)}.", ""]
    required = set(schema.get("required", []))
    rows = (
        (
            f"`{field}`",
            describe_type(item) + ("" if field in required else ", optional"),
            _words_of(item),
        )
        for field, item in properties.items()
    )
    return [*lines, *_table(["Field", "Kind", "What it says"], rows), ""]


def _route_rows(operations: Sequence[tuple[str, str, Schema]]) -> Iterable[Sequence[str]]:
    for method, path, operation in operations:
        title = _title_of(operation)
        yield method.upper(), f"`{path}`", f"[{title}](#{anchor_of(title)})"


def _headings(lines: Iterable[str]) -> list[str]:
    return [line.lstrip("#").strip() for line in lines if re.match(r"#{2,3} ", line)]


def _refuse_repeated_headings(lines: Iterable[str]) -> None:
    counts = Counter(anchor_of(heading) for heading in _headings(lines))
    repeated = sorted(anchor for anchor, count in counts.items() if count > 1)
    if repeated:
        raise DocumentError(f"two headings share the link #{repeated[0]}, so rename one of them")


def render_endpoints(spec: Schema) -> str:
    """The page that lists every route and every model."""
    schemes = spec.get("components", {}).get("securitySchemes", {})
    operations = _operations(spec)
    lines = [
        "# Endpoint reference",
        "",
        NOTICE,
        "",
        _words_of(spec["info"]).strip(),
        "",
        ENDPOINTS_INTRO,
        "",
        "## All routes",
        "",
        *_table(["Method", "Path", "What it does"], _route_rows(operations)),
        "",
    ]
    for tag in spec.get("tags", []):
        lines += [f"## Routes for {tag['name']}", "", _words_of(tag), ""]
        for method, path, operation in operations:
            if tag["name"] in operation.get("tags", []):
                lines += render_operation(method, path, operation, schemes)
    models: Mapping[str, Schema] = spec.get("components", {}).get("schemas", {})
    lines += ["## Models", ""]
    for name in sorted(models):
        lines += render_schema(name, models[name])
    _refuse_repeated_headings(lines)
    return "\n".join(lines).rstrip() + "\n"


def _default_of(setting: SettingDoc) -> str:
    if setting.required:
        return "required"
    if setting.default is None:
        return "not set"
    return f"`{format_value(setting.default)}`"


def _section_heading(section: Section) -> str:
    if not section.path:
        return "Settings at the top of the file"
    return f"The `{'.'.join(section.path)}` table"


def render_settings(sections: Sequence[Section]) -> str:
    """The page that lists every setting with its variable, kind, default, and meaning."""
    lines = [
        "# Settings reference",
        "",
        NOTICE,
        "",
        SETTINGS_INTRO,
        "",
    ]
    for section in sections:
        if not section.settings:
            continue
        lines += [f"## {_section_heading(section)}", ""]
        if section.description:
            lines += [section.description, ""]
        rows = (
            (f"`{item.key}`", f"`{item.variable}`", item.kind, _default_of(item), item.explanation)
            for item in section.settings
        )
        lines += [*_table(["Setting", "Variable", "Kind", "Default", "What it does"], rows), ""]
    return "\n".join(lines).rstrip() + "\n"


def documents(root: Path) -> dict[Path, str]:
    """Every generated page and the text it should hold."""
    docs = root / "docs"
    spec = openapi_document()
    return {
        docs / "openapi.json": json.dumps(spec, indent=2) + "\n",
        docs / "endpoints.md": render_endpoints(spec),
        docs / "settings.md": render_settings(catalog()),
    }


def _current(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the pages that come from the code.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing, and fail when a page differs from what the code produces",
    )
    parser.add_argument(
        "--root", type=Path, default=ROOT, help="the folder of the project, which holds docs/"
    )
    arguments = parser.parse_args(argv)
    try:
        wanted = documents(arguments.root)
    except DocumentError as error:
        sys.stderr.write(f"gen_docs: {error}\n")
        return 1
    stale = [path for path, text in wanted.items() if _current(path) != text]
    if arguments.check:
        for path in stale:
            name = path.relative_to(arguments.root).as_posix()
            sys.stderr.write(f"gen_docs: {name} is out of date, run `{REFRESH_COMMAND}`\n")
        if stale:
            return 1
        sys.stdout.write(f"gen_docs ok pages={len(wanted)}\n")
        return 0
    for path in stale:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(wanted[path], encoding="utf-8", newline="\n")
        sys.stdout.write(f"wrote {path.relative_to(arguments.root).as_posix()}\n")
    if not stale:
        sys.stdout.write("the pages are current\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
