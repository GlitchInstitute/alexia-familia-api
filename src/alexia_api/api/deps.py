"""What the routes need from the application, found through the request."""

from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Request

from alexia_api.clock import Clock
from alexia_api.config import Settings
from alexia_api.services.keys import ApiKeyStore
from alexia_api.services.ratelimit import RateLimiter
from alexia_api.services.registry import Registry


@dataclass(frozen=True, slots=True)
class Services:
    """The long-lived parts of the server. The app factory builds them once."""

    settings: Settings
    registry: Registry
    keys: ApiKeyStore
    limiter: RateLimiter
    clock: Clock


def get_services(request: Request) -> Services:
    return cast("Services", request.app.state.services)


ServicesDep = Annotated[Services, Depends(get_services)]
