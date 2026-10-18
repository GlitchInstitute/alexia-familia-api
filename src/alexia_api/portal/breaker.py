"""The block that stops automatic logins after a failure that can lock the account.

A restart must not forget the block, or a crash loop would try the password again and again. The
file holds the cause and the time, never a credential. A file that cannot be read counts as a
block, because the safe answer to "did a login fail?" is yes.
"""

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from alexia_api.clock import Clock, SystemClock
from alexia_api.domain.accounts import Blocked
from alexia_api.domain.ids import AccountId, parse_account_id

log = logging.getLogger(__name__)


class BreakerStore:
    def __init__(self, directory: Path, clock: Clock | None = None) -> None:
        self._directory = directory
        self._clock = clock or SystemClock()

    def read(self, account: AccountId) -> Blocked | None:
        path = self._path(account)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            return self._unreadable(path)
        try:
            return Blocked.model_validate_json(text)
        except ValidationError:
            return self._unreadable(path)

    def write(self, account: AccountId, blocked: Blocked) -> None:
        path = self._path(account)
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self._directory, prefix=".breaker-")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(blocked.model_dump_json())
            Path(temporary).replace(path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def clear(self, account: AccountId) -> None:
        self._path(account).unlink(missing_ok=True)

    def _path(self, account: AccountId) -> Path:
        return self._directory / f"{parse_account_id(account)}.json"

    def _unreadable(self, path: Path) -> Blocked:
        log.warning("the block file %s cannot be read, so the account stays blocked", path.name)
        return Blocked(cause="state_unreadable", since=self._now())

    def _now(self) -> datetime:
        return self._clock.now()
