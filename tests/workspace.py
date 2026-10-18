"""The files an operator has on disk, written the way the commands and the server expect them."""

from datetime import UTC, datetime
from pathlib import Path

from alexia_api.domain.accounts import Blocked
from alexia_api.domain.errors import BreakerCause
from alexia_api.domain.ids import parse_account_id
from alexia_api.portal.breaker import BREAKER_DIRECTORY, BreakerStore
from alexia_api.services.keys import FILE_NAME, ApiKeyStore

ENVIRON = {"MARTA_USER": "marta.ejemplo", "MARTA_PASSWORD": "demo-password-a"}
HEALTHY_ACCOUNT = """
[accounts.marta]
portal_url = "http://localhost:8081"
institution_key = "demo-school"
username = "env:MARTA_USER"
password = "env:MARTA_PASSWORD"
"""


def write_config(
    directory: Path,
    *,
    top: str = "",
    account: str = HEALTHY_ACCOUNT,
    state: Path | None = None,
) -> Path:
    path = directory / "alexia-api.toml"
    chosen = state or directory / "state"
    path.write_text(f'state_dir = "{chosen.as_posix()}"\n{top}\n{account}', encoding="utf-8")
    return path


def make_key(directory: Path, name: str = "phone", accounts: tuple[str, ...] = ("*",)) -> None:
    ApiKeyStore(directory / "state" / FILE_NAME).create(name, scopes=["read"], accounts=accounts)


def block(directory: Path, cause: BreakerCause) -> None:
    BreakerStore(directory / "state" / BREAKER_DIRECTORY).write(
        parse_account_id("marta"),
        Blocked(cause=cause, since=datetime(2026, 10, 18, 20, 15, tzinfo=UTC)),
    )
