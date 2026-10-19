"""Check a body against a schema of the OpenAPI document."""

from typing import Any

from openapi_schema_validator import OAS31Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from alexia_api.api.app import openapi_document

DOCUMENT_URI = "urn:alexia-api:openapi"
DOCUMENT = openapi_document()


def validator_for(schema: dict[str, Any]) -> OAS31Validator:
    """A validator for a `$ref` to a model of the document, which is where the model is found."""
    registry: Registry[Any] = Registry().with_resource(
        DOCUMENT_URI, Resource.from_contents(DOCUMENT, default_specification=DRAFT202012)
    )
    reference = {"$ref": f"{DOCUMENT_URI}#{schema['$ref'].removeprefix('#')}"}
    return OAS31Validator(reference, registry=registry)


def validate_against_model(body: object, schema: dict[str, Any]) -> None:
    """Raise when the body does not fit the schema."""
    validator_for(schema).validate(body)
