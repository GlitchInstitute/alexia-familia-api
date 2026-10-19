"""A simulated portal plus everything needed to open sessions and gateways against it."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import SecretStr

from alexia_api.clock import ManualClock
from alexia_api.config import AccountSettings, Settings
from alexia_api.domain.errors import PortalError, PortalErrorDetail
from alexia_api.domain.ids import RoleId, StudentId, parse_account_id, parse_student_id
from alexia_api.domain.messages import FolderName, MessageSummary
from alexia_api.portal.breaker import BreakerStore
from alexia_api.portal.gateway import Gateway
from alexia_api.portal.inbox import read_feed
from alexia_api.portal.login import PortalCredentials
from alexia_api.portal.session import Gates, PortalSession
from alexia_api.services.registry import Registry
from alexia_api.sim.app import PortalSim
from alexia_api.sim.mail import SimMessage
from alexia_api.sim.world import (
    DEMO_PASSWORD_A,
    DEMO_PASSWORD_B,
    DEMO_USER_A,
    DEMO_USER_B,
    SIM_INSTITUTION_KEY,
    SimChild,
    SimStaff,
    default_world,
    synthetic_guid,
)

type Failure = Callable[[Awaitable[object]], Awaitable[PortalErrorDetail]]

A_NEW_SIBLING = SimChild(
    student_id=synthetic_guid(0x103),
    person_id=synthetic_guid(0x203),
    full_name="Inés Ejemplo Muestra",
    first_name="Inés",
    relation="Hija",
)

A_NEW_MESSAGE = replace(
    default_world().families[0].messages[0],
    guid=synthetic_guid(0x1100),
    subject="Nuevo aviso",
    date="2026-10-17",
    read=False,
)


def seeded(number: int, username: str = DEMO_USER_A) -> SimMessage:
    """A message that the simulator's world holds for a family from the start."""
    family = default_world().family_for(username)
    assert family is not None
    return next(message for message in family.messages if message.guid == synthetic_guid(number))


def teacher(number: int) -> SimStaff:
    """A member of the staff in the simulator's world, found by the number of their id."""
    return next(
        member
        for family in default_world().families
        for child in family.children
        for member in child.staff
        if member.id == synthetic_guid(number)
    )


async def listed_row(
    gateway: Gateway, number: int, folder: FolderName = "received"
) -> MessageSummary:
    """The row that a folder list shows for a message of the simulator's world."""
    feed = await gateway.call(lambda tx: read_feed(tx, folder))
    return next(row for row in feed.messages if row.id == synthetic_guid(number))


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
    registries: list[Registry] = field(default_factory=list)

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

    def session(self, gates: Gates | None = None, zone: ZoneInfo | None = None) -> PortalSession:
        session = PortalSession(
            self.sim.base_url,
            transport=self.sim.transport(),
            clock=self.clock,
            gates=gates,
            zone=zone,
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
        zone: ZoneInfo | None = None,
    ) -> Gateway:
        return Gateway(
            account=parse_account_id(account),
            session=self.session(gates, zone),
            credentials=credentials if credentials is not None else self.credentials(),
            breaker=BreakerStore(state_dir or self.state_dir, self.clock),
            clock=self.clock,
            role_id=role_id,
            fresh_for=fresh_for,
        )

    def guardian_of(self, first_name: str) -> tuple[Gateway, StudentId]:
        """A gateway for the guardian of a child of the default world, and the child's id."""
        for family in default_world().families:
            for child in family.children:
                if child.first_name == first_name:
                    gateway = self.gateway(
                        account=family.guardian.first_name.lower(),
                        credentials=self.credentials(family.username, family.password),
                    )
                    return gateway, parse_student_id(child.student_id)
        raise LookupError(first_name)

    def account_settings(
        self,
        username: str = DEMO_USER_A,
        password: str = DEMO_PASSWORD_A,
        **overrides: Any,
    ) -> AccountSettings:
        return AccountSettings(
            portal_url=self.sim.base_url,
            institution_key=SIM_INSTITUTION_KEY,
            username=SecretStr(username),
            password=SecretStr(password),
            **overrides,
        )

    def settings(self, **overrides: Any) -> Settings:
        """Settings for two accounts, `marta` and `pablo`, unless `accounts` says otherwise."""
        accounts = (
            overrides.pop("accounts")
            if "accounts" in overrides
            else {
                "marta": self.account_settings(),
                "pablo": self.account_settings(DEMO_USER_B, DEMO_PASSWORD_B),
            }
        )
        return Settings(accounts=accounts, **{"state_dir": self.state_dir, **overrides})

    def registry(
        self, settings: Settings | None = None, *, environ: Mapping[str, str] | None = None
    ) -> Registry:
        registry = Registry.build(
            settings or self.settings(),
            environ=environ or {},
            clock=self.clock,
            transport_for=lambda _account: self.sim.transport(),
        )
        self.registries.append(registry)
        return registry

    def requests_to(self, suffix: str) -> int:
        return sum(1 for request in self.sim.requests if request.path.endswith(suffix))

    def enrol(self, username: str, child: SimChild) -> None:
        """The school adds a child to a family. A session that is already open sees it next."""
        world = self.sim.world
        families = tuple(
            replace(family, children=(*family.children, child))
            if family.username == username
            else family
            for family in world.families
        )
        self.sim.world = replace(world, families=families)

    def revise_child(self, username: str, student_id: str, **changes: Any) -> None:
        """The school changes what it holds about a child. An open session sees it next."""
        world = self.sim.world
        families = tuple(
            replace(
                family,
                children=tuple(
                    replace(child, **changes) if child.student_id == student_id else child
                    for child in family.children
                ),
            )
            if family.username == username
            else family
            for family in world.families
        )
        self.sim.world = replace(world, families=families)

    def revise(self, username: str, guid: str, **changes: Any) -> None:
        """The school changes a message it sent. A session that is already open sees it next."""
        world = self.sim.world
        families = tuple(
            replace(
                family,
                messages=tuple(
                    replace(message, **changes) if message.guid == guid else message
                    for message in family.messages
                ),
            )
            if family.username == username
            else family
            for family in world.families
        )
        self.sim.world = replace(world, families=families)

    def withdraw(self, username: str, guid: str) -> None:
        """The school takes back a message it sent. A session that is already open sees it next."""
        world = self.sim.world
        families = tuple(
            replace(family, messages=tuple(m for m in family.messages if m.guid != guid))
            if family.username == username
            else family
            for family in world.families
        )
        self.sim.world = replace(world, families=families)

    def deliver(self, username: str, message: SimMessage) -> None:
        """The school sends a family a message. A session that is already open sees it next."""
        world = self.sim.world
        families = tuple(
            replace(family, messages=(*family.messages, message))
            if family.username == username
            else family
            for family in world.families
        )
        self.sim.world = replace(world, families=families)
