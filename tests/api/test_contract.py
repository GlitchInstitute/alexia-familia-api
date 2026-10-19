"""Every answer the API gives is the one that its OpenAPI document promises.

The document and the answers come from the same models, so this test looks at the places where
they can part, such as a problem document that the application builds by hand. It sends a request
to every route of the document and checks the answer against the schema, the media type, and the
headers that the document names.
"""

from typing import Any

import httpx
import pytest
from openapi_schema_validator import OAS31Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from alexia_api.api.app import openapi_document
from tests.api.support import Api, bearer

DOCUMENT_URI = "urn:alexia-api:openapi"
JSON_MEDIA_TYPES = {"application/json", "application/problem+json"}
DOCUMENT = openapi_document()
OPERATIONS = [
    (method, path)
    for path, item in DOCUMENT["paths"].items()
    for method in item
    if method in {"get", "post", "put", "patch", "delete"}
]


def validate_against_model(body: object, schema: dict[str, Any]) -> None:
    """Check a body against a schema of the document. A `$ref` finds its model in the document."""
    registry: Registry[Any] = Registry().with_resource(
        DOCUMENT_URI, Resource.from_contents(DOCUMENT, default_specification=DRAFT202012)
    )
    reference = {"$ref": f"{DOCUMENT_URI}#{schema['$ref'].removeprefix('#')}"}
    OAS31Validator(reference, registry=registry).validate(body)


async def concrete_values(api: Api) -> dict[str, str]:
    """Names that exist in the simulated world, one for each path parameter of the document."""
    listing = (await api.get("/v1/accounts/marta/messages?limit=100")).json()
    with_file = next(item["id"] for item in listing["items"] if item["has_attachments"])
    message = (await api.get(f"/v1/accounts/marta/messages/{with_file}")).json()
    return {
        "account": "marta",
        "child": "lucia",
        "message": with_file,
        "attachment": message["attachments"][0]["id"],
    }


def media_type_of(response: httpx.Response) -> str:
    return response.headers["content-type"].split(";")[0].strip()


def promised(operation: dict[str, Any], status: int) -> dict[str, Any]:
    responses: dict[str, Any] = operation["responses"]
    assert str(status) in responses, f"the document has no {status} answer for this route"
    answer: dict[str, Any] = responses[str(status)]
    return answer


async def ask(api: Api, method: str, path: str, **kwargs: Any) -> httpx.Response:
    return await api.client.request(method.upper(), path, **kwargs)


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
async def test_the_answer_of_a_route_matches_its_schema_media_type_and_headers(
    api: Api, method: str, path: str
) -> None:
    operation = DOCUMENT["paths"][path][method]
    concrete = path.format(**await concrete_values(api))

    response = await ask(api, method, concrete, headers=bearer(api.admin_key))

    assert response.status_code == 200, response.text
    answer = promised(operation, 200)
    media = media_type_of(response)
    assert media in answer.get("content", {}) or "*/*" in answer.get("content", {}), media
    if media in JSON_MEDIA_TYPES:
        validate_against_model(response.json(), answer["content"][media]["schema"])
    for header in answer.get("headers", {}):
        assert header.lower() in response.headers, f"{header} is documented but not sent"


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
async def test_a_refusal_of_a_route_is_a_problem_that_the_document_describes(
    api: Api, method: str, path: str
) -> None:
    operation = DOCUMENT["paths"][path][method]
    values = await concrete_values(api)
    unknown_account = {**values, "account": "nobody"}
    refusals: list[tuple[int, str, dict[str, str]]] = []
    if operation.get("security"):
        refusals.append((401, path.format(**values), {}))
    if "{account}" in path:
        refusals.append((404, path.format(**unknown_account), bearer(api.admin_key)))

    for status, concrete, headers in refusals:
        response = await ask(api, method, concrete, headers=headers)

        assert response.status_code == status, response.text
        assert media_type_of(response) == "application/problem+json"
        schema = promised(operation, status)["content"]["application/problem+json"]["schema"]
        validate_against_model(response.json(), schema)
