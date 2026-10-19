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
from alexia_api.domain.agenda import EVENT_KINDS
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


async def test_every_tag_an_operation_uses_is_described(api: Api) -> None:
    schema = await schema_of(api)
    described = {tag["name"] for tag in schema["tags"] if tag.get("description")}
    used = {tag for _, _, operation in operations(schema) for tag in operation["tags"]}

    assert used <= described


async def test_the_operation_ids_read_well_in_a_generated_client(api: Api) -> None:
    ids = {operation["operationId"] for _, _, operation in operations(await schema_of(api))}
    assert {
        "list_accounts",
        "list_children",
        "get_tracking",
        "list_absences",
        "list_meetings",
        "list_available_days",
        "list_available_hours",
        "check_connection",
        "list_folders",
        "list_messages",
        "get_message",
        "download_attachment",
        "list_forms",
        "get_form",
        "get_child_agenda",
        "get_guardian_agenda",
        "get_child_calendar",
        "get_guardian_calendar",
        "get_family_calendar",
    } <= ids


async def test_both_ways_to_send_a_key_are_documented(api: Api) -> None:
    schemes = (await schema_of(api))["components"]["securitySchemes"]
    assert (schemes["BearerKey"]["type"], schemes["BearerKey"]["scheme"]) == ("http", "bearer")
    header = schemes["HeaderKey"]
    assert (header["type"], header["in"], header["name"]) == ("apiKey", "header", "X-API-Key")


async def test_only_the_versioned_operations_ask_for_a_key(api: Api) -> None:
    for path, _, operation in operations(await schema_of(api)):
        assert bool(operation.get("security")) == path.startswith("/v1/"), path


async def test_the_calendar_routes_alone_take_a_key_in_the_url(api: Api) -> None:
    schema = await schema_of(api)
    feed = schema["components"]["securitySchemes"]["FeedKey"]
    assert (feed["type"], feed["in"], feed["name"]) == ("apiKey", "query", "key")
    assert "feed" in feed["description"]
    calendars = {
        "/v1/accounts/{account}/children/{child}/agenda.ics",
        "/v1/accounts/{account}/guardian/agenda.ics",
        "/v1/accounts/{account}/agenda.ics",
    }
    for path, _, operation in operations(schema):
        takes_a_key_in_the_url = {"FeedKey": []} in operation.get("security", [])
        assert takes_a_key_in_the_url == (path in calendars), path


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


@pytest.mark.parametrize("path", ["/healthz", "/readyz"])
async def test_a_probe_route_documents_that_it_ignores_the_host_name(api: Api, path: str) -> None:
    operation = (await schema_of(api))["paths"][path]["get"]
    assert "any host name" in operation["description"]


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
        "/v1/accounts/{account}/children/{child}/absences",
        "/v1/accounts/{account}/children/{child}/meetings",
        "/v1/accounts/{account}/children/{child}/staff/{staff}/availability",
        "/v1/accounts/{account}/children/{child}/staff/{staff}/availability/{day}",
        "/v1/accounts/{account}/children/{child}/agenda",
        "/v1/accounts/{account}/guardian/agenda",
        "/v1/accounts/{account}/children/{child}/agenda.ics",
        "/v1/accounts/{account}/guardian/agenda.ics",
        "/v1/accounts/{account}/agenda.ics",
        "/v1/accounts/{account}/folders",
        "/v1/accounts/{account}/messages",
        "/v1/accounts/{account}/messages/{message}",
        "/v1/accounts/{account}/forms",
        "/v1/accounts/{account}/forms/{form}",
    ):
        headers = paths[path]["get"]["responses"]["200"]["headers"]
        assert set(headers) == {"X-Cache", "Age"}, path


async def test_every_parameter_is_explained(api: Api) -> None:
    for path, method, operation in operations(await schema_of(api)):
        for parameter in operation.get("parameters", []):
            assert parameter.get("description"), (method, path, parameter["name"])


async def test_the_message_list_documents_its_folders_and_its_page_limits(api: Api) -> None:
    operation = (await schema_of(api))["paths"]["/v1/accounts/{account}/messages"]["get"]
    parameters = {parameter["name"]: parameter["schema"] for parameter in operation["parameters"]}

    assert parameters["folder"]["enum"] == ["received", "sent"]
    assert (parameters["limit"]["minimum"], parameters["limit"]["maximum"]) == (1, 100)
    assert parameters["offset"]["minimum"] == 0


async def test_the_message_route_documents_its_folder_and_what_opening_may_do(api: Api) -> None:
    operation = (await schema_of(api))["paths"]["/v1/accounts/{account}/messages/{message}"]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}

    assert parameters["folder"]["schema"]["enum"] == ["received", "sent"]
    assert parameters["message"]["in"] == "path"
    assert "may mark it as read" in operation["description"]


async def test_the_download_route_documents_a_file_and_how_it_is_saved(api: Api) -> None:
    path = "/v1/accounts/{account}/messages/{message}/attachments/{attachment}"
    operation = (await schema_of(api))["paths"][path]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    ok = operation["responses"]["200"]

    assert ok["content"] == {"*/*": {"schema": {"type": "string", "format": "binary"}}}
    assert set(ok["headers"]) == {"Content-Disposition"}
    assert {"404", "413", "502", "503", "504"} <= set(operation["responses"])
    assert parameters["attachment"]["in"] == "path"
    assert parameters["folder"]["schema"]["enum"] == ["received", "sent"]
    assert "attachment_too_large" in operation["description"]


async def test_the_agenda_documents_its_range_its_kinds_and_its_limits(api: Api) -> None:
    operation = (await schema_of(api))["paths"]["/v1/accounts/{account}/children/{child}/agenda"][
        "get"
    ]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}

    assert {"account", "child", "from", "to", "kind", "fresh"} == set(parameters)
    assert "date" in json.dumps(parameters["from"]["schema"])
    assert "date" in json.dumps(parameters["to"]["schema"])
    kinds = json.dumps(parameters["kind"]["schema"])
    assert all(kind in kinds for kind in EVENT_KINDS)
    assert "366 days" in operation["description"]
    assert "1100 days" in operation["description"]
    assert "invalid_window" in operation["description"]


async def test_the_absences_route_documents_what_the_list_can_and_cannot_tell(api: Api) -> None:
    path = "/v1/accounts/{account}/children/{child}/absences"
    operation = (await schema_of(api))["paths"][path]["get"]

    assert {"account", "child", "fresh"} == {item["name"] for item in operation["parameters"]}
    assert {"401", "403", "404", "422", "429", "500", "502", "503", "504"} <= set(
        operation["responses"]
    )
    assert "does not prove" in operation["description"]
    assert "portal_changed" in operation["description"]


async def test_the_meetings_route_documents_which_words_it_knows(api: Api) -> None:
    path = "/v1/accounts/{account}/children/{child}/meetings"
    operation = (await schema_of(api))["paths"][path]["get"]

    assert {"account", "child", "fresh"} == {item["name"] for item in operation["parameters"]}
    assert "`unknown`" in operation["description"]
    assert "`state_label`" in operation["description"]
    assert "portal_changed" in operation["description"]


async def test_the_forms_routes_document_what_they_read_and_what_they_do_not(api: Api) -> None:
    paths = (await schema_of(api))["paths"]
    prefix = "/v1/accounts/{account}/forms"
    forms, form = paths[prefix]["get"], paths[f"{prefix}/{{form}}"]["get"]

    assert {item["name"] for item in forms["parameters"]} == {"account", "fresh"}
    assert {item["name"] for item in form["parameters"]} == {"account", "form", "fresh"}
    for operation in (forms, form):
        assert {"401", "403", "404", "422", "429", "500", "502", "503", "504"} <= set(
            operation["responses"]
        )
    assert "cannot tell whether a form was answered" in forms["description"]
    assert "ends the session" in forms["description"]
    assert "portal_changed" in forms["description"]
    assert "unexpected_reply" in forms["description"]
    assert "may mark it as read" in form["description"]
    assert "are not served" in form["description"]


async def test_the_availability_routes_document_their_parameters_and_refusals(api: Api) -> None:
    paths = (await schema_of(api))["paths"]
    prefix = "/v1/accounts/{account}/children/{child}/staff/{staff}/availability"
    days, hours = paths[prefix]["get"], paths[f"{prefix}/{{day}}"]["get"]

    day_names = {item["name"] for item in days["parameters"]}
    hour_names = {item["name"] for item in hours["parameters"]}
    assert day_names == {"account", "child", "staff", "month", "fresh"}
    assert hour_names == {"account", "child", "staff", "day", "fresh"}
    month = next(item for item in days["parameters"] if item["name"] == "month")
    assert "pattern" in json.dumps(month["schema"])
    for operation in (days, hours):
        assert {"401", "403", "404", "422", "429", "500", "502", "503", "504"} <= set(
            operation["responses"]
        )
        assert "invalid_window" in operation["description"]
        assert "1100 days" in operation["description"]
    assert "staff_not_found" in days["description"]


async def test_the_guardian_agenda_documents_the_login_that_has_no_guardian(api: Api) -> None:
    operation = (await schema_of(api))["paths"]["/v1/accounts/{account}/guardian/agenda"]["get"]
    assert "guardian_not_found" in operation["description"]
    assert {"401", "403", "404", "422", "429", "500", "502", "503", "504"} <= set(
        operation["responses"]
    )


@pytest.mark.parametrize(
    "path",
    [
        "/v1/accounts/{account}/children/{child}/agenda.ics",
        "/v1/accounts/{account}/guardian/agenda.ics",
        "/v1/accounts/{account}/agenda.ics",
    ],
)
async def test_a_calendar_route_documents_its_file_its_reach_and_its_key(
    api: Api, path: str
) -> None:
    operation = (await schema_of(api))["paths"][path]["get"]
    parameters = {parameter["name"]: parameter["schema"] for parameter in operation["parameters"]}

    assert operation["responses"]["200"]["content"] == {
        "text/calendar": {"schema": {"type": "string"}}
    }
    assert {"401", "403", "404", "422", "429", "500", "502", "503", "504"} <= set(
        operation["responses"]
    )
    assert "--scope feed" in operation["description"]
    for name, default in (("back", 14), ("ahead", 180), ("lessons_ahead", 90)):
        if name in parameters:
            schema = parameters[name]
            assert (schema["minimum"], schema["maximum"], schema["default"]) == (0, 366, default)
    assert {"back", "ahead"} <= set(parameters)
    assert "fresh" not in parameters


async def test_the_problem_schema_lists_what_a_client_can_rely_on(api: Api) -> None:
    problem = (await schema_of(api))["components"]["schemas"]["Problem"]
    assert set(problem["required"]) == {"type", "title", "status", "detail", "code", "request_id"}
    assert problem["properties"]["type"]["const"] == "about:blank"


async def test_a_field_with_a_default_is_required_because_every_answer_carries_it(
    api: Api,
) -> None:
    schemas = (await schema_of(api))["components"]["schemas"]
    assert schemas["LoggedOut"]["required"] == ["state"]
    assert {"state", "cause", "since", "interstitial"} == set(schemas["Blocked"]["required"])


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
