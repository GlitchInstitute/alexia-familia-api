"""The API keys that may call this server.

A key is shown once, when it is made. The file keeps only its SHA-256 hash. That is enough to
check a key, because a key is 256 random bits and cannot be guessed from its hash. The command
line writes the file and the server rereads it when it changes, so a new or revoked key takes
effect without a restart. A file that cannot be read refuses every key, and it is never
overwritten, because a half-fixed file is the operator's to look at.
"""

import hashlib
import hmac
import logging
import os
import re
import secrets
import tempfile
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pydantic import AwareDatetime, Field

from alexia_api.clock import Clock, SystemClock
from alexia_api.domain.base import Model
from alexia_api.domain.ids import MAX_SLUG_LENGTH, SLUG_PATTERN, InvalidIdError, parse_account_id
from alexia_api.domain.security import ALL_ACCOUNTS, SCOPES, Principal, Scope

log = logging.getLogger(__name__)

KEY_PREFIX: Final = "afk_"
FILE_NAME: Final = "api-keys.json"
_NAME: Final = re.compile(SLUG_PATTERN)
_SECRET_BYTES: Final = 32


class KeyStoreError(Exception):
    """The key file cannot be used, or a request to change it makes no sense."""


class ApiKeyRecord(Model):
    """What the file keeps about one key. The key itself is not here, only its hash."""

    name: str = Field(description="The operator's name for the key. It appears in logs.")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="The hash of the key.")
    scopes: list[Scope] = Field(min_length=1, description="The kinds of access the key holds.")
    accounts: list[str] = Field(min_length=1, description='The accounts it may use, or ["*"].')
    created_at: AwareDatetime


class _KeyFile(Model):
    version: Literal[1] = 1
    keys: list[ApiKeyRecord] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class IssuedKey:
    """A new key. This is the only time the key itself exists outside the client."""

    key: str
    record: ApiKeyRecord


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()


type _Signature = tuple[int, int, int]


class ApiKeyStore:
    def __init__(self, path: Path, clock: Clock | None = None) -> None:
        self._path = path
        self._clock = clock or SystemClock()
        self._seen: tuple[_Signature, tuple[ApiKeyRecord, ...] | str] | None = None

    def create(self, name: str, *, scopes: Collection[str], accounts: Collection[str]) -> IssuedKey:
        """Make a key, store its hash, and return the key. It cannot be shown again."""
        records = self._read()
        if len(name) > MAX_SLUG_LENGTH or _NAME.fullmatch(name) is None:
            raise KeyStoreError(
                f"a key name is 1 to {MAX_SLUG_LENGTH} lower case letters, digits, and hyphens"
            )
        if any(record.name == name for record in records):
            raise KeyStoreError(f"a key named {name} already exists")
        record_scopes = _check_scopes(scopes)
        record_accounts = _check_accounts(accounts)
        key = KEY_PREFIX + secrets.token_urlsafe(_SECRET_BYTES)
        record = ApiKeyRecord(
            name=name,
            sha256=hash_key(key),
            scopes=record_scopes,
            accounts=record_accounts,
            created_at=self._clock.now(),
        )
        self._write((*records, record))
        return IssuedKey(key=key, record=record)

    def revoke(self, name: str) -> bool:
        """Remove a key. Returns whether there was one with that name."""
        records = self._read()
        kept = tuple(record for record in records if record.name != name)
        if len(kept) == len(records):
            return False
        self._write(kept)
        return True

    def records(self) -> tuple[ApiKeyRecord, ...]:
        """Every key the file holds, without the keys themselves."""
        return self._read()

    def authenticate(self, presented: str) -> Principal | None:
        """Find who holds a key.

        Every stored hash is compared, so the answer takes the same time whichever key matches.
        """
        try:
            records = self._read()
        except KeyStoreError:
            return None
        digest = hash_key(presented)
        found: ApiKeyRecord | None = None
        for record in records:
            if hmac.compare_digest(record.sha256, digest):
                found = record
        if found is None:
            return None
        return Principal(
            key_name=found.name,
            scopes=frozenset(found.scopes),
            accounts=frozenset(found.accounts),
        )

    def _read(self) -> tuple[ApiKeyRecord, ...]:
        """The keys in the file, read again only when the file changed."""
        try:
            info = self._path.stat()
        except FileNotFoundError:
            self._seen = None
            return ()
        except OSError:
            raise KeyStoreError(f"{FILE_NAME} cannot be read") from None
        signature = (info.st_mtime_ns, info.st_size, info.st_ino)
        if self._seen is None or self._seen[0] != signature:
            outcome = self._parse()
            self._seen = (signature, outcome)
            if isinstance(outcome, str):
                log.warning("%s, so every API key is refused until it is fixed", outcome)
        outcome = self._seen[1]
        if isinstance(outcome, str):
            raise KeyStoreError(f"{outcome}, fix or remove the file first")
        return outcome

    def _parse(self) -> tuple[ApiKeyRecord, ...] | str:
        try:
            return tuple(_KeyFile.model_validate_json(self._path.read_text("utf-8")).keys)
        except (ValueError, OSError):
            return f"{FILE_NAME} cannot be read"

    def _write(self, records: tuple[ApiKeyRecord, ...]) -> None:
        directory = self._path.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".api-keys-")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(_KeyFile(keys=list(records)).model_dump_json(indent=2) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary).replace(self._path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        info = self._path.stat()
        self._seen = ((info.st_mtime_ns, info.st_size, info.st_ino), records)


def _check_scopes(scopes: Collection[str]) -> list[Scope]:
    if not scopes:
        raise KeyStoreError("a key needs at least one scope")
    unknown = sorted(set(scopes) - set(SCOPES))
    if unknown:
        raise KeyStoreError(f"unknown scope {unknown[0]}, use one of {', '.join(SCOPES)}")
    return sorted(scope for scope in SCOPES if scope in scopes)


def _check_accounts(accounts: Collection[str]) -> list[str]:
    if not accounts:
        raise KeyStoreError("a key needs at least one account, or * for all of them")
    if ALL_ACCOUNTS in accounts:
        return [ALL_ACCOUNTS]
    for account in accounts:
        try:
            parse_account_id(account)
        except InvalidIdError:
            raise KeyStoreError(f"{account} is not a valid account name") from None
    return sorted(accounts)
