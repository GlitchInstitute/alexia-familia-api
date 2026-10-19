"""The accounts this server serves, each with one gateway and one cache.

A child is always found through its account's own listing. A key for one account therefore cannot
reach a student id that the portal did not list for that login, whatever id the caller sends.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Self

import httpx

from alexia_api.clock import Clock, LocalClock, SystemClock
from alexia_api.config import AccountSettings, CacheTtls, Settings, resolve_secrets
from alexia_api.domain.accounts import Account, Capabilities
from alexia_api.domain.children import Child, Guardian, StaffMember, TrackingCounters, apply_pins
from alexia_api.domain.ids import (
    AccountId,
    ChildSlug,
    InvalidIdError,
    StudentId,
    parse_account_id,
    parse_attachment_id,
    parse_message_id,
    parse_role_id,
)
from alexia_api.domain.media import Download
from alexia_api.domain.messages import Folder, FolderName, Message, MessageSummary
from alexia_api.domain.security import Principal
from alexia_api.portal.attachments import download_attachment
from alexia_api.portal.breaker import BREAKER_DIRECTORY, BreakerStore
from alexia_api.portal.children import read_home
from alexia_api.portal.folders import read_folder_tree
from alexia_api.portal.gateway import CheckResult, Gateway
from alexia_api.portal.inbox import Feed, read_feed
from alexia_api.portal.login import PortalCredentials
from alexia_api.portal.message import read_message
from alexia_api.portal.roster import read_roster
from alexia_api.portal.session import Gates, PortalSession
from alexia_api.portal.tracking import read_tracking
from alexia_api.services.cache import Cached, TtlCache, combine
from alexia_api.services.errors import NotFoundError

type TransportFactory = Callable[[AccountSettings], httpx.AsyncBaseTransport | None]

MAX_CACHED_MESSAGES: Final = 32
"""How many messages with their words an account keeps. A message with pictures can take several
mebibytes, so these are kept apart from the lists, which a long run of reads must not push out."""


@dataclass(frozen=True, slots=True)
class Directory:
    """The guardian and the children that one login lists, with their final slugs."""

    guardian: Guardian | None
    children: tuple[Child, ...]


class AccountRuntime:
    """What the server holds for one account."""

    def __init__(
        self,
        *,
        account: AccountId,
        settings: AccountSettings,
        gateway: Gateway,
        cache: TtlCache,
        message_cache: TtlCache,
        ttls: CacheTtls,
        capabilities: Capabilities,
        max_attachment_bytes: int,
    ) -> None:
        self.account = account
        self.label = settings.label or account
        self._host = settings.portal_host
        self._pins: Mapping[StudentId, ChildSlug] = settings.pinned_slugs()
        self._gateway = gateway
        self._cache = cache
        self._message_cache = message_cache
        self._ttls = ttls
        self._capabilities = capabilities
        self._max_attachment_bytes = max_attachment_bytes

    async def status(self) -> Account:
        """Describe the account without calling the portal."""
        return Account(
            id=self.account,
            label=self.label,
            portal_host=self._host,
            connection=await self._gateway.refresh(),
            capabilities=self._capabilities,
            child_count=self._gateway.child_count,
        )

    async def directory(self, *, fresh: bool = False) -> Cached[Directory]:
        return await self._cache.get(
            ("directory",), self._ttls.children, self._read_directory, fresh=fresh
        )

    async def child(self, reference: str, *, fresh: bool = False) -> Cached[Child]:
        """Find a child by student id or slug.

        A missing child is reported from the cached listing, because a lookup that missed must not
        send a request to the portal. A client that expects a new sibling reads the list of
        children with `fresh` first.
        """
        listing = await self.directory(fresh=fresh)
        wanted = reference.lower()
        children = listing.value.children
        found = next((child for child in children if child.id == wanted), None) or next(
            (child for child in children if child.slug == wanted), None
        )
        if found is None:
            raise NotFoundError("child", reference)
        return Cached(found, listing.status, listing.age)

    async def tracking(self, child: Child, *, fresh: bool = False) -> Cached[TrackingCounters]:
        return await self._cache.get(
            ("tracking", child.id),
            self._ttls.tracking,
            lambda: self._gateway.call(lambda tx: read_tracking(tx, child.id)),
            fresh=fresh,
        )

    async def staff(self, child: Child, *, fresh: bool = False) -> Cached[tuple[StaffMember, ...]]:
        async def load() -> tuple[StaffMember, ...]:
            return tuple(await self._gateway.call(lambda tx: read_roster(tx, child.id)))

        return await self._cache.get(("staff", child.id), self._ttls.staff, load, fresh=fresh)

    async def folders(self, *, fresh: bool = False) -> Cached[tuple[Folder, ...]]:
        return await self._cache.get(
            ("folders",),
            self._ttls.folders,
            lambda: self._gateway.call(read_folder_tree),
            fresh=fresh,
        )

    async def messages(self, folder: FolderName, *, fresh: bool = False) -> Cached[Feed]:
        """Every message of a folder, newest first.

        The whole listing is kept, so a client that pages through it costs the portal one read.
        """
        return await self._cache.get(
            ("messages", folder),
            self._ttls.messages,
            lambda: self._gateway.call(lambda tx: read_feed(tx, folder)),
            fresh=fresh,
        )

    async def _listed(
        self, folder: FolderName, reference: str, *, fresh: bool
    ) -> tuple[MessageSummary, Cached[Feed]]:
        """The row of a message in the stored list of its folder, with that list.

        A reference that is no message id, or that the portal did not list for this login, is not
        found without a request to the portal. A client that expects a message that arrived lately
        reads with `fresh`.
        """
        try:
            wanted = parse_message_id(reference)
        except InvalidIdError:
            raise NotFoundError("message", reference) from None
        listing = await self.messages(folder, fresh=fresh)
        row = next((summary for summary in listing.value.messages if summary.id == wanted), None)
        if row is None:
            raise NotFoundError("message", reference)
        return row, listing

    async def message(
        self, folder: FolderName, reference: str, *, fresh: bool = False
    ) -> Cached[Message]:
        """One message of a folder, with its words.

        The row comes from the list as it is now and the words come from a store of their own, so
        `read` agrees with the list even when the words are older.
        """
        row, listing = await self._listed(folder, reference, fresh=fresh)
        content = await self._message_cache.get(
            ("message", row.id),
            self._ttls.message,
            lambda: self._gateway.call(lambda tx: read_message(tx, row)),
            fresh=fresh,
        )
        return combine(Message.of(row, content.value), listing, content)

    async def attachment(
        self, folder: FolderName, reference: str, attachment: str, *, fresh: bool = False
    ) -> Download:
        """One file of a message, fetched from the portal every time and never stored.

        A message or a token that cannot name anything is not found without a request to the
        portal. A token the message does not list is found out from the live page. `fresh` only
        makes the list that holds the message be read again, because the file is always live.
        """
        row, _ = await self._listed(folder, reference, fresh=fresh)
        try:
            token = parse_attachment_id(attachment)
        except InvalidIdError:
            raise NotFoundError("attachment", attachment) from None
        download = await self._gateway.call(
            lambda tx: download_attachment(tx, row, token, self._max_attachment_bytes)
        )
        if download is None:
            raise NotFoundError("attachment", attachment)
        return download

    async def check(self, *, fresh: bool = False) -> CheckResult:
        """Make sure a session works, logging in if needed. This is the one call that logs in."""
        return await self._gateway.check(fresh=fresh)

    async def reset_block(self) -> bool:
        """Lift the block after a person fixed its cause. Returns whether there was a block."""
        return await self._gateway.reset_breaker()

    async def aclose(self) -> None:
        await self._gateway.aclose()

    async def _read_directory(self) -> Directory:
        home = await self._gateway.call(read_home)
        return Directory(guardian=home.guardian, children=apply_pins(home.children, self._pins))


class Registry:
    def __init__(self, runtimes: Iterable[AccountRuntime]) -> None:
        self._runtimes = {runtime.account: runtime for runtime in runtimes}

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        environ: Mapping[str, str],
        clock: Clock | None = None,
        transport_for: TransportFactory | None = None,
    ) -> Self:
        """Open one gateway per configured account.

        Every secret is read before any session opens, so a missing variable stops the server
        before it holds a connection. Nothing here calls the portal. The first request does.
        """
        clock = LocalClock(clock or SystemClock(), settings.tzinfo)
        secrets = resolve_secrets(settings, environ)
        gates = Gates(
            writes=settings.allow_writes,
            restore_unread=settings.restore_unread,
            forms=settings.allow_forms,
        )
        breaker = BreakerStore(settings.state_dir / BREAKER_DIRECTORY, clock)
        runtimes = []
        for name, account in settings.accounts.items():
            account_id = parse_account_id(name)
            user, password = secrets[name]
            session = PortalSession(
                account.base_url,
                gates=gates,
                transport=transport_for(account) if transport_for else None,
                clock=clock,
                zone=settings.tzinfo,
                min_spacing=settings.min_spacing_seconds,
                timeout=settings.request_timeout_seconds,
            )
            gateway = Gateway(
                account=account_id,
                session=session,
                credentials=PortalCredentials(
                    user=user, password=password, institution_key=account.key
                ),
                breaker=breaker,
                clock=clock,
                role_id=parse_role_id(account.role_id) if account.role_id else None,
            )
            runtimes.append(
                AccountRuntime(
                    account=account_id,
                    settings=account,
                    gateway=gateway,
                    cache=TtlCache(clock),
                    message_cache=TtlCache(clock, max_entries=MAX_CACHED_MESSAGES),
                    ttls=settings.cache,
                    capabilities=settings.capabilities,
                    max_attachment_bytes=settings.max_attachment_bytes,
                )
            )
        return cls(runtimes)

    @property
    def accounts(self) -> tuple[AccountRuntime, ...]:
        return tuple(self._runtimes.values())

    def get(self, account: str) -> AccountRuntime:
        try:
            return self._runtimes[parse_account_id(account)]
        except (InvalidIdError, KeyError):
            raise NotFoundError("account", account) from None

    def visible_to(self, principal: Principal) -> tuple[AccountRuntime, ...]:
        return tuple(runtime for runtime in self.accounts if principal.sees(runtime.account))

    async def aclose(self) -> None:
        for runtime in self.accounts:
            await runtime.aclose()
