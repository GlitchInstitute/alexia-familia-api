"""The base class for every model that crosses the API boundary."""

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """Frozen, so one instance is safe to share between requests, and strict about unknown input."""

    model_config = ConfigDict(frozen=True, extra="forbid")
