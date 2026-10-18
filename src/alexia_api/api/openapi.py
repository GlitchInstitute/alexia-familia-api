"""Corrections to the OpenAPI document that FastAPI generates.

FastAPI documents a 422 with its own error shape and documents every error body as plain JSON.
This API answers with problem documents under their own media type, so the generated document
would describe responses that never happen. The fixes run once, when the document is first built.
"""

from collections.abc import Iterator
from typing import Any, Final

from fastapi import FastAPI

from alexia_api.api.errors import PROBLEM_MEDIA_TYPE, UNPROCESSABLE, title_of

_PROBLEM_REF: Final = "#/components/schemas/Problem"
_FASTAPI_VALIDATION_SCHEMAS: Final = ("HTTPValidationError", "ValidationError")
_JSON: Final = "application/json"


def _responses(schema: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if isinstance(operation, dict):
                yield from operation.get("responses", {}).items()


def describe_validation_failures_as_problems(schema: dict[str, Any]) -> None:
    for status, response in _responses(schema):
        if status == str(UNPROCESSABLE):
            response["description"] = title_of(UNPROCESSABLE)
            response["content"] = {_JSON: {"schema": {"$ref": _PROBLEM_REF}}}
    components = schema.get("components", {}).get("schemas", {})
    for name in _FASTAPI_VALIDATION_SCHEMAS:
        components.pop(name, None)


def move_problems_to_their_media_type(schema: dict[str, Any]) -> None:
    for status, response in _responses(schema):
        content = response.get("content", {})
        body = content.get(_JSON)
        is_problem = body is not None and body.get("schema", {}).get("$ref") == _PROBLEM_REF
        if status.isdigit() and int(status) >= 400 and is_problem:
            content[PROBLEM_MEDIA_TYPE] = content.pop(_JSON)


def install_openapi(app: FastAPI) -> None:
    """Make the app build its OpenAPI document with the corrections applied."""
    generate = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = generate()
        describe_validation_failures_as_problems(schema)
        move_problems_to_their_media_type(schema)
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
