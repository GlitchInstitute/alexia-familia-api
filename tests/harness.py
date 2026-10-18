"""A simulated portal plus everything needed to open sessions and gateways against it."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pydantic import SecretStr

from alexia_api.clock import ManualClock
from alexia_api.domain.errors import PortalError, PortalErrorDetail
from alexia_api.domain.ids import RoleId, parse_account_id
from alexia_api.portal.breaker import BreakerStore
from alexia_api.portal.gateway import Gateway
from alexia_api.portal.login import PortalCredentials
from alexia_api.portal.session import Gates, PortalSession
from alexia_api.sim.app import PortalSim
from alexia_api.sim.world import DEMO_PASSWORD_A, DEMO_USER_A, SIM_INSTITUTION_KEY

type Failure = Callable[[Awaitable[object]], Awaitable[PortalErrorDetail]]


async def failure_of(awaitable: Awaitable[object]) -> PortalErrorDetail:
    """Await something that must fail with a `PortalError` and hand back its typed reason."""
    with pytest.raises(PortalError) as raised:
        await awaitable
    return raised.value.detail


@dataclass
class Harness:
    sim: PortalSim
    clock: ManualClock
    state_dir: Path
    opened: list[PortalSession] = field(default_factory=list)

    def credentials(
        self,
        username: str = DEMO_USER_A,
        password: str = DEMO_PASSWORD_A,
        institution_key: str = SIM_INSTITUTION_KEY,
    ) -> PortalCredentials:
        return PortalCredentials(
            user=SecretStr(username),
            password=SecretStr(password),
            institution_key=institution_key,
        )

    def session(self, gates: Gates | None = None) -> PortalSession:
        session = PortalSession(
            self.sim.base_url,
            transport=self.sim.transport(),
            clock=self.clock,
            gates=gates,
        )
        self.opened.append(session)
        return session

    def gateway(
        self,
        *,
        account: str = "family-a",
        credentials: PortalCredentials | None = None,
        gates: Gates | None = None,
        role_id: RoleId | None = None,
        fresh_for: float = 600.0,
        state_dir: Path | None = None,
    ) -> Gateway:
        return Gateway(
            account=parse_account_id(account),
            session=self.session(gates),
            credentials=credentials if credentials is not None else self.credentials(),
            breaker=BreakerStore(state_dir or self.state_dir, self.clock),
            clock=self.clock,
            role_id=role_id,
            fresh_for=fresh_for,
        )

    def requests_to(self, suffix: str) -> int:
        return sum(1 for request in self.sim.requests if request.path.endswith(suffix))
