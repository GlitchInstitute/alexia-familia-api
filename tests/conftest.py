"""Shared fixtures. They build a simulated portal and gateways that talk to it in process."""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from hypothesis import settings

from alexia_api.clock import ManualClock
from alexia_api.sim.app import PortalSim
from alexia_api.sim.world import default_world
from tests.harness import Failure, Harness, failure_of

settings.register_profile("dev")
settings.register_profile("ci", derandomize=True, database=None, print_blob=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture(autouse=True)
def _no_settings_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's own ALEXIA_API_* variables out of every test."""
    for name in [name for name in os.environ if name.startswith("ALEXIA_API_")]:
        monkeypatch.delenv(name)


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
    for registry in harness.registries:
        await registry.aclose()
