import json
from typing import Any

import pytest
from openapi_spec_validator import validate
from openapi_spec_validator.validation.exceptions import OpenAPIValidationError

from alexia_api import __version__
from alexia_api.api.app import openapi_document
from alexia_api.api.openapi import (
    describe_validation_failures_as_problems,
    move_problems_to_their_media_type,
)
from tests.api.support import Api, MakeApi, problem_of

PROBLEM_REF = "#/components/schemas/Problem"
PROBLEM_TYPE = "application/problem+json"


async def schema_of(api: Api) -> dict[str, Any]:
    response = await api.client.get("/openapi.json")
    assert response.status_code == 200
    document: dict[str, Any] = response.json()
    return document


def operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, operation)
        for path, item in schema["paths"].items()
        for method, operation in item.items()
    ]


async def test_the_document_names_the_server_and_its_version(api: Api) -> None:
    schema = await schema_of(api)
    assert schema["openapi"].startswith("3.1")
    assert schema["info"]["title"] == "alexia-familia-api"
    assert schema["info"]["version"] == __version__
    assert "unofficial" in schema["info"]["description"]


async def test_every_operation_is_explained_and_has_its_own_id(api: Api) -> None:
    listed = operations(await schema_of(api))
    ids = [operation["operationId"] for _, _, operation in listed]
    assert len(ids) == len(set(ids))
    for path, method, operation in listed:
        assert operation["summary"], (method, path)
        assert operation["description"], (method, path)
        assert operation["tags"], (method, path)


async def test_the_operation_ids_read_well_in_a_generated_client(api: Api) -> None:
    ids = {operation["operationId"] for _, _, operation in operations(await schema_of(api))}
    assert {"list_accounts", "list_children", "get_tracking", "check_connection"} <= ids


async def test_both_ways_to_send_a_key_are_documented(api: Api) -> None:
    schemes = (await schema_of(api))["components"]["securitySchemes"]
    assert (schemes["BearerKey"]["type"], schemes["BearerKey"]["scheme"]) == ("http", "bearer")
    header = schemes["HeaderKey"]
    assert (header["type"], header["in"], header["name"]) == ("apiKey", "header", "X-API-Key")


async def test_only_the_versioned_operations_ask_for_a_key(api: Api) -> None:
    for path, _, operation in operations(await schema_of(api)):
        assert bool(operation.get("security")) == path.startswith("/v1/"), path


async def test_no_validation_schema_of_the_framework_is_left(api: Api) -> None:
    schema = await schema_of(api)
    names = set(schema["components"]["schemas"])
    assert "HTTPValidationError" not in names
    assert "ValidationError" not in names
    assert "Problem" in names


async def test_a_422_is_described_as_a_problem(api: Api) -> None:
    found = [
        operation["responses"]["422"]
        for _, _, operation in operations(await schema_of(api))
        if "422" in operation["responses"]
    ]
    assert found
    for response in found:
        assert response["content"] == {PROBLEM_TYPE: {"schema": {"$ref": PROBLEM_REF}}}


async def test_every_error_is_described_under_the_problem_media_type(api: Api) -> None:
    for path, method, operation in operations(await schema_of(api)):
        for status, response in operation["responses"].items():
            if int(status) >= 400 and path != "/readyz":
                assert list(response["content"]) == [PROBLEM_TYPE], (method, path, status)


async def test_readiness_documents_its_own_503_and_not_a_problem(api: Api) -> None:
    schema = await schema_of(api)
    response = schema["paths"]["/readyz"]["get"]["responses"]["503"]
    assert list(response["content"]) == ["application/json"]


async def test_the_failures_a_client_can_meet_are_listed_for_each_route(api: Api) -> None:
    paths = (await schema_of(api))["paths"]
    accounts = paths["/v1/accounts"]["get"]["responses"]
    tracking = paths["/v1/accounts/{account}/children/{child}/tracking"]["get"]["responses"]
    assert {"401", "403", "429", "500"} <= set(accounts)
    assert {"401", "403", "404", "422", "429", "500", "502", "503", "504"} <= set(tracking)


async def test_cached_reads_document_their_cache_headers(api: Api) -> None:
    paths = (await schema_of(api))["paths"]
    for path in (
        "/v1/accounts/{account}/children",
        "/v1/accounts/{account}/children/{child}",
        "/v1/accounts/{account}/children/{child}/tracking",
        "/v1/accounts/{account}/children/{child}/staff",
    ):
        headers = paths[path]["get"]["responses"]["200"]["headers"]
        assert set(headers) == {"X-Cache", "Age"}, path


async def test_the_problem_schema_lists_what_a_client_can_rely_on(api: Api) -> None:
    problem = (await schema_of(api))["components"]["schemas"]["Problem"]
    assert {"title", "status", "detail", "code", "request_id"} <= set(problem["required"])
    assert "type" not in problem["required"]
    assert problem["properties"]["type"]["default"] == "about:blank"


def test_the_document_follows_the_openapi_standard() -> None:
    validate(openapi_document())


def test_the_validator_refuses_a_document_that_breaks_the_standard() -> None:
    document = openapi_document()
    del document["info"]

    with pytest.raises(OpenAPIValidationError):
        validate(document)


async def test_the_document_without_a_server_is_the_one_a_server_serves(api: Api) -> None:
    assert openapi_document() == await schema_of(api)


@pytest.mark.parametrize(
    "changes",
    [
        {"docs_enabled": False},
        {"allow_writes": True},
        {"cors_origins": ["https://app.example.test"]},
        {"rate_limit_per_minute": 5},
    ],
    ids=lambda changes: next(iter(changes)),
)
async def test_no_setting_changes_the_document(make_api: MakeApi, changes: dict[str, Any]) -> None:
    api = await make_api(**changes)

    assert api.app.openapi() == openapi_document()


async def test_the_document_is_built_once_and_served_from_then_on(api: Api) -> None:
    assert api.app.openapi() is api.app.openapi()
    first = json.dumps(await schema_of(api), sort_keys=True)
    second = json.dumps(await schema_of(api), sort_keys=True)
    assert first == second


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_the_documentation_is_served_by_default(api: Api, path: str) -> None:
    assert (await api.client.get(path)).status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"])
async def test_the_documentation_can_be_switched_off(make_api: MakeApi, path: str) -> None:
    api = await make_api(docs_enabled=False)
    response = await api.client.get(path)
    problem_of(response, status=404, code="not_found")
    assert "content-security-policy" in response.headers


def test_a_422_that_is_not_there_is_left_alone() -> None:
    schema: dict[str, Any] = {
        "paths": {"/x": {"get": {"responses": {"200": {"description": "fine"}}}}},
        "components": {"schemas": {"Other": {}}},
    }
    describe_validation_failures_as_problems(schema)
    assert schema["paths"]["/x"]["get"]["responses"] == {"200": {"description": "fine"}}
    assert schema["components"]["schemas"] == {"Other": {}}


def test_problems_move_but_other_bodies_and_the_default_response_stay() -> None:
    def body(reference: str) -> dict[str, Any]:
        return {"application/json": {"schema": {"$ref": reference}}}

    other = "#/components/schemas/Other"
    schema: dict[str, Any] = {
        "paths": {
            "/x": {
                "parameters": [],
                "get": {
                    "responses": {
                        "200": {"content": body(other)},
                        "400": {"content": body(other)},
                        "404": {"content": body(PROBLEM_REF)},
                        "default": {"content": body(PROBLEM_REF)},
                        "204": {"description": "no body"},
                    }
                },
            }
        }
    }
    move_problems_to_their_media_type(schema)
    responses = schema["paths"]["/x"]["get"]["responses"]
    assert list(responses["404"]["content"]) == [PROBLEM_TYPE]
    assert list(responses["200"]["content"]) == ["application/json"]
    assert list(responses["400"]["content"]) == ["application/json"]
    assert list(responses["default"]["content"]) == ["application/json"]
    assert "content" not in responses["204"]
