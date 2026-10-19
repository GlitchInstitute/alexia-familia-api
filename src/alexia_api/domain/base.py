"""The base class for every model that crosses the API boundary."""

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """Frozen, so one instance is safe to share between requests, and strict about unknown input.

    A response always carries every field of its model, including the ones that have a default,
    so the OpenAPI document lists them as required and a generated client does not mark them
    optional.
    """

    model_config = ConfigDict(
        frozen=True, extra="forbid", json_schema_serialization_defaults_required=True
    )
