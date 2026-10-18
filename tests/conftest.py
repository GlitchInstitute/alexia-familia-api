"""Shared fixtures. They build a simulated portal and gateways that talk to it in process."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from alexia_api.clock import ManualClock
from alexia_api.sim.app import PortalSim
from alexia_api.sim.world import default_world
from tests.harness import Failure, Harness, failure_of


@pytest.fixture
def failure() -> Failure:
    return failure_of


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
async def harness(clock: ManualClock, tmp_path: Path) -> AsyncIterator[Harness]:
    harness = Harness(
        sim=PortalSim(default_world(), clock=clock),
        clock=clock,
        state_dir=tmp_path / "state",
    )
    yield harness
    for session in harness.opened:
        await session.aclose()
