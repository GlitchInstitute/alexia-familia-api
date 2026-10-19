"""The gateway signs in when it must, trusts a session for a while, and stops when unsafe."""

import asyncio
from itertools import pairwise
from typing import TYPE_CHECKING

import pytest

from alexia_api.domain.accounts import Blocked, Connection, LoggedIn, LoggedOut
from alexia_api.domain.errors import (
    ActionRequiredInPortal,
    BreakerOpen,
    InvalidCredentials,
    NoCredentials,
    PortalError,
    PortalMaintenance,
    SessionExpired,
    TokenInvalid,
)
from alexia_api.domain.ids import parse_account_id
from alexia_api.portal.breaker import BreakerStore
from alexia_api.portal.children import read_home
from alexia_api.portal.gateway import Gateway
from alexia_api.portal.session import DEFAULT_SPACING_SECONDS, Tx
from alexia_api.sim.app import BAD_CREDENTIALS_TEXT
from alexia_api.sim.world import DEMO_PASSWORD_B, DEMO_USER_B
from tests.harness import Failure, Harness

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def connection_of(gateway: Gateway) -> Connection:
    """Read the connection fresh each time, so type narrowing does not carry across awaits."""
    return gateway.connection


async def always_expired(_tx: Tx) -> None:
    raise PortalError(SessionExpired())


async def test_the_first_call_signs_in_then_runs_the_recipe(harness: Harness) -> None:
    gateway = harness.gateway()
    assert isinstance(connection_of(gateway), LoggedOut)

    snapshot = await gateway.call(read_home)

    assert len(snapshot.children) == 2
    assert isinstance(connection_of(gateway), LoggedIn)
    assert harness.requests_to("/Validar") == 1


async def test_a_call_inside_the_fresh_window_does_not_probe_or_sign_in_again(
    harness: Harness,
) -> None:
    gateway = harness.gateway()
    await gateway.call(read_home)
    harness.clock.advance(5 * 60)

    await gateway.call(read_home)

    assert harness.requests_to("/Validar") == 1
    assert harness.sim.counters.check_session_calls == 0


async def test_an_older_session_is_probed_before_it_is_trusted(harness: Harness) -> None:
    gateway = harness.gateway()
    await gateway.call(read_home)
    harness.clock.advance(11 * 60)

    await gateway.call(read_home)

    assert harness.sim.counters.check_session_calls == 1
    assert harness.requests_to("/Validar") == 1


async def test_it_signs_in_again_when_the_probe_says_the_session_is_gone(
    harness: Harness,
) -> None:
    gateway = harness.gateway()
    await gateway.call(read_home)
    harness.clock.advance(25 * 60)

    await gateway.call(read_home)

    assert harness.sim.counters.check_session_calls == 1
    assert harness.requests_to("/Validar") == 2


async def test_a_session_that_expires_mid_recipe_is_renewed_once(harness: Harness) -> None:
    gateway = harness.gateway()
    await gateway.call(read_home)
    harness.sim.expire_all_sessions()

    snapshot = await gateway.call(read_home)

    assert len(snapshot.children) == 2
    assert harness.requests_to("/Validar") == 2


async def test_it_gives_up_when_the_renewed_session_expires_again(
    harness: Harness, failure: Failure
) -> None:
    gateway = harness.gateway()

    detail = await failure(gateway.call(always_expired))

    assert detail == SessionExpired()
    assert harness.requests_to("/Validar") == 2


async def test_a_wrong_password_blocks_the_account_after_one_attempt(
    harness: Harness, failure: Failure
) -> None:
    gateway = harness.gateway(credentials=harness.credentials(password="wrong"))

    detail = await failure(gateway.call(read_home))

    assert detail == InvalidCredentials(portal_text=BAD_CREDENTIALS_TEXT)
    blocked = connection_of(gateway)
    assert isinstance(blocked, Blocked)
    assert blocked.cause == "invalid_credentials"
    seen = len(harness.sim.requests)

    again = await failure(gateway.call(read_home))

    assert isinstance(again, BreakerOpen)
    assert again.cause == "invalid_credentials"
    assert len(harness.sim.requests) == seen


async def test_a_block_survives_a_restart_until_someone_resets_it(
    harness: Harness, failure: Failure
) -> None:
    wrong = harness.gateway(credentials=harness.credentials(password="wrong"))
    await failure(wrong.call(read_home))
    seen = len(harness.sim.requests)

    restarted = harness.gateway()
    assert isinstance(connection_of(restarted), Blocked)
    assert isinstance(await failure(restarted.call(read_home)), BreakerOpen)
    assert len(harness.sim.requests) == seen

    assert await restarted.reset_breaker() is True
    snapshot = await restarted.call(read_home)

    assert len(snapshot.children) == 2
    assert isinstance(connection_of(restarted), LoggedIn)
    assert isinstance(connection_of(harness.gateway()), LoggedOut)


async def test_resetting_an_account_that_is_not_blocked_says_so(harness: Harness) -> None:
    assert await harness.gateway().reset_breaker() is False


async def test_a_running_gateway_notices_a_block_lifted_on_disk(
    harness: Harness, failure: Failure
) -> None:
    harness.sim.options.multifactor = True
    gateway = harness.gateway()
    await failure(gateway.call(read_home))
    assert isinstance(connection_of(gateway), Blocked)

    harness.sim.options.multifactor = False
    BreakerStore(harness.state_dir, harness.clock).clear(parse_account_id("family-a"))
    snapshot = await gateway.call(read_home)

    assert len(snapshot.children) == 2
    assert isinstance(connection_of(gateway), LoggedIn)


async def test_a_block_lifted_on_disk_shows_in_the_status_without_calling_the_portal(
    harness: Harness, failure: Failure
) -> None:
    harness.sim.options.multifactor = True
    gateway = harness.gateway()
    await failure(gateway.call(read_home))
    seen = len(harness.sim.requests)

    assert isinstance(await gateway.refresh(), Blocked)
    BreakerStore(harness.state_dir, harness.clock).clear(parse_account_id("family-a"))

    assert isinstance(await gateway.refresh(), LoggedOut)
    assert len(harness.sim.requests) == seen


async def test_a_block_that_is_still_on_disk_stays_in_force(
    harness: Harness, failure: Failure
) -> None:
    harness.sim.options.multifactor = True
    gateway = harness.gateway()
    await failure(gateway.call(read_home))
    seen = len(harness.sim.requests)

    assert isinstance(await failure(gateway.call(read_home)), BreakerOpen)
    assert isinstance(await gateway.refresh(), Blocked)
    assert len(harness.sim.requests) == seen


async def test_a_multifactor_prompt_blocks_the_account(harness: Harness, failure: Failure) -> None:
    harness.sim.options.multifactor = True
    gateway = harness.gateway()

    await failure(gateway.call(read_home))

    blocked = connection_of(gateway)
    assert isinstance(blocked, Blocked)
    assert blocked.cause == "mfa_required"


async def test_a_step_in_the_portal_blocks_the_account_and_remembers_which(
    harness: Harness, failure: Failure
) -> None:
    harness.sim.options.interstitial = "CambiarPws"
    gateway = harness.gateway()

    detail = await failure(gateway.call(read_home))

    assert detail == ActionRequiredInPortal(interstitial="CambiarPws")
    blocked = connection_of(gateway)
    assert isinstance(blocked, Blocked)
    assert blocked.interstitial == "CambiarPws"


async def test_an_outage_does_not_block_the_account(harness: Harness, failure: Failure) -> None:
    harness.sim.options.maintenance = "http503"
    gateway = harness.gateway()

    detail = await failure(gateway.call(read_home))

    assert detail == PortalMaintenance(status=503)
    assert isinstance(connection_of(gateway), LoggedOut)

    harness.sim.options.maintenance = "none"
    await gateway.call(read_home)

    assert isinstance(connection_of(gateway), LoggedIn)


async def test_a_stale_token_that_will_not_clear_does_not_block_the_account(
    harness: Harness, failure: Failure
) -> None:
    harness.sim.counters.token_failures_left = 2
    gateway = harness.gateway()

    assert await failure(gateway.call(read_home)) == TokenInvalid()
    assert isinstance(connection_of(gateway), LoggedOut)


async def test_missing_credentials_are_reported_and_do_not_block(
    harness: Harness, failure: Failure
) -> None:
    gateway = Gateway(
        account=parse_account_id("family-a"),
        session=harness.session(),
        credentials=None,
        breaker=BreakerStore(harness.state_dir, harness.clock),
        clock=harness.clock,
    )

    assert await failure(gateway.call(read_home)) == NoCredentials()
    assert isinstance(connection_of(gateway), LoggedOut)
    assert harness.sim.requests == []


async def test_calls_never_overlap_and_share_one_login(harness: Harness) -> None:
    gateway = harness.gateway()

    results = await asyncio.gather(*(gateway.call(read_home) for _ in range(5)))

    assert all(len(snapshot.children) == 2 for snapshot in results)
    assert harness.sim.max_in_flight == 1
    assert harness.requests_to("/Validar") == 1


@pytest.mark.parametrize("again", ["call", "check", "reset"])
async def test_a_recipe_that_asks_its_own_gateway_for_another_turn_is_refused_and_not_left_waiting(
    harness: Harness, again: str
) -> None:
    gateway = harness.gateway()
    asks: dict[str, Callable[[], Awaitable[object]]] = {
        "call": lambda: gateway.call(read_home),
        "check": gateway.check,
        "reset": gateway.reset_breaker,
    }

    async def recipe(_tx: Tx) -> None:
        await asks[again]()

    async with asyncio.timeout(5):
        with pytest.raises(RuntimeError, match="another turn"):
            await gateway.call(recipe)
        assert len((await gateway.call(read_home)).children) == 2


async def test_a_recipe_may_use_the_gateway_of_another_account(harness: Harness) -> None:
    first = harness.gateway()
    second = harness.gateway(
        account="family-b", credentials=harness.credentials(DEMO_USER_B, DEMO_PASSWORD_B)
    )

    async def recipe(_tx: Tx) -> int:
        return len((await second.call(read_home)).children)

    async with asyncio.timeout(5):
        assert await first.call(recipe) == 2


async def test_requests_are_spaced_by_the_politeness_delay(harness: Harness) -> None:
    await harness.gateway().call(read_home)

    starts = [request.at for request in harness.sim.requests]
    gaps = [later - earlier for earlier, later in pairwise(starts)]
    assert len(starts) == 6
    assert all(gap >= DEFAULT_SPACING_SECONDS - 1e-9 for gap in gaps)


async def test_check_reports_whether_the_session_was_new_or_reused(harness: Harness) -> None:
    gateway = harness.gateway()

    first = await gateway.check()
    second = await gateway.check()
    forced = await gateway.check(fresh=True)

    assert (first.session, first.child_count) == ("new", 2)
    assert (second.session, second.child_count) == ("reused", 2)
    assert forced.session == "new"


async def test_the_connection_tracks_the_last_success(harness: Harness) -> None:
    gateway = harness.gateway()
    await gateway.call(read_home)
    first = connection_of(gateway)
    assert isinstance(first, LoggedIn)

    harness.clock.advance(30)
    await gateway.call(read_home)

    later = connection_of(gateway)
    assert isinstance(later, LoggedIn)
    assert later.since == first.since
    assert later.last_success_at > first.last_success_at


@pytest.mark.parametrize("fresh_for", [0.0, 1.0])
async def test_a_short_trust_window_probes_on_the_next_call(
    harness: Harness, fresh_for: float
) -> None:
    gateway = harness.gateway(fresh_for=fresh_for)
    await gateway.call(read_home)
    harness.clock.advance(5)

    await gateway.call(read_home)

    assert harness.sim.counters.check_session_calls == 1
    assert harness.requests_to("/Validar") == 1
