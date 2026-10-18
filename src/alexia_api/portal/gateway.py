"""The one door to the portal for a single account.

The gateway owns the session, the login, and the breaker. It runs one recipe at a time, because
the portal keeps state per session. It logs in when it has to, probes an old session before it
trusts it, retries once after a session expires, and stops logging in after a failure that could
lock the account.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from alexia_api.clock import Clock, SystemClock
from alexia_api.domain.accounts import Blocked, Connection, LoggedIn, LoggedOut
from alexia_api.domain.errors import (
    ActionRequiredInPortal,
    BreakerOpen,
    NoCredentials,
    PortalError,
    SessionExpired,
    breaker_cause,
)
from alexia_api.domain.ids import AccountId, RoleId
from alexia_api.portal import wire
from alexia_api.portal.allowlist import CHECK_SESSION
from alexia_api.portal.breaker import BreakerStore
from alexia_api.portal.login import LoginOk, PortalCredentials, login
from alexia_api.portal.session import PortalSession, Tx
from alexia_api.portal.ws import call_ws

if TYPE_CHECKING:
    from datetime import datetime

    from alexia_api.portal.children import HomeSnapshot

SESSION_FRESH_SECONDS: Final = 10 * 60
IDLE_MINUTES_REPORTED: Final = 1


@dataclass(frozen=True, slots=True)
class CheckResult:
    session: Literal["new", "reused"]
    child_count: int | None


class Gateway:
    def __init__(
        self,
        *,
        account: AccountId,
        session: PortalSession,
        credentials: PortalCredentials | None,
        breaker: BreakerStore,
        clock: Clock | None = None,
        role_id: RoleId | None = None,
        fresh_for: float = SESSION_FRESH_SECONDS,
    ) -> None:
        self._account = account
        self._session = session
        self._credentials = credentials
        self._breaker = breaker
        self._clock = clock or SystemClock()
        self._role_id = role_id
        self._fresh_for = fresh_for
        self._lock = asyncio.Lock()
        self._blocked: Blocked | None = breaker.read(account)
        self._logged_in_at: datetime | None = None
        self._last_ok_at: datetime | None = None
        self._last_ok_tick: float | None = None
        self._home: HomeSnapshot | None = None

    @property
    def connection(self) -> Connection:
        if self._blocked is not None:
            return self._blocked
        if self._logged_in_at is not None and self._last_ok_at is not None:
            return LoggedIn(since=self._logged_in_at, last_success_at=self._last_ok_at)
        return LoggedOut()

    @property
    def child_count(self) -> int | None:
        return len(self._home.children) if self._home is not None else None

    async def call[T](self, work: Callable[[Tx], Awaitable[T]]) -> T:
        """Run a recipe with the session held, logging in first and once more if it expired."""
        async with self._lock:
            await self._ensure(fresh=False)
            try:
                result = await work(self._session)
            except PortalError as error:
                if not isinstance(error.detail, SessionExpired):
                    raise
                await self._ensure(fresh=True)
                result = await work(self._session)
            self._touch()
            return result

    async def check(self, *, fresh: bool = False) -> CheckResult:
        """Make sure there is a working session, logging in if needed, and report which."""
        async with self._lock:
            state = await self._ensure(fresh=fresh)
            return CheckResult(session=state, child_count=self.child_count)

    async def refresh(self) -> Connection:
        """Report the connection after checking whether someone lifted the block on disk.

        This never calls the portal, so a status page costs the school nothing.
        """
        await self._forget_a_lifted_block()
        return self.connection

    async def reset_breaker(self) -> bool:
        """Lift a block after a person fixed the cause. Returns whether there was one."""
        async with self._lock:
            was_blocked = self._blocked is not None
            self._blocked = None
            await asyncio.to_thread(self._breaker.clear, self._account)
            return was_blocked

    async def aclose(self) -> None:
        await self._session.aclose()

    def _touch(self) -> None:
        self._last_ok_at = self._clock.now()
        self._last_ok_tick = self._clock.monotonic()

    async def _forget_a_lifted_block(self) -> None:
        """Drop the in-memory block when the file is gone, so the command line can lift it.

        Another login may write a new block while the file is being read, so the old block is
        dropped only if it is still the one that was seen before the read.
        """
        observed = self._blocked
        if observed is None:
            return
        on_disk = await asyncio.to_thread(self._breaker.read, self._account)
        if on_disk is None and self._blocked is observed:
            self._blocked = None

    async def _ensure(self, *, fresh: bool) -> Literal["new", "reused"]:
        await self._forget_a_lifted_block()
        if self._blocked is not None:
            raise PortalError(BreakerOpen(since=self._blocked.since, cause=self._blocked.cause))
        if not fresh and self._last_ok_tick is not None:
            if self._clock.monotonic() - self._last_ok_tick < self._fresh_for:
                return "reused"
            if await self._alive():
                self._touch()
                return "reused"
        await self._login()
        return "new"

    async def _alive(self) -> bool:
        try:
            reply = await call_ws(
                self._session,
                CHECK_SESSION,
                wire.CheckSessionParams(counter=IDLE_MINUTES_REPORTED),
            )
        except PortalError:
            return False
        return reply.is_ok

    async def _login(self) -> None:
        if self._credentials is None:
            raise PortalError(NoCredentials())
        self._last_ok_tick = None
        try:
            ok: LoginOk = await login(self._session, self._credentials, role_id=self._role_id)
        except PortalError as error:
            self._logged_in_at = None
            self._last_ok_at = None
            cause = breaker_cause(error.detail)
            if cause is not None:
                blocked = Blocked(
                    cause=cause,
                    since=self._clock.now(),
                    interstitial=(
                        error.detail.interstitial
                        if isinstance(error.detail, ActionRequiredInPortal)
                        else None
                    ),
                )
                await asyncio.to_thread(self._breaker.write, self._account, blocked)
                self._blocked = blocked
            raise
        self._home = ok.home
        self._logged_in_at = self._clock.now()
        self._touch()
