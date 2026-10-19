"""A server that talks to a simulated school, so anyone can try the API without an account.

The families, the children, and everything they show are made up. The simulator runs in this
process, so the demo needs no second server and no network. The settings are fixed values, so a
person's own `ALEXIA_API_` variables can never put a real account into the demo. The key is made
when the demo starts, in a folder that the caller throws away when the demo stops.
"""

import signal
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Final, NoReturn

from fastapi import FastAPI
from pydantic import SecretStr

from alexia_api.api.app import create_app
from alexia_api.clock import Clock
from alexia_api.config import AccountSettings, FixedSettings, Settings
from alexia_api.domain.ids import attachment_token
from alexia_api.domain.security import ALL_ACCOUNTS
from alexia_api.services.keys import FILE_NAME, ApiKeyStore
from alexia_api.services.registry import Registry
from alexia_api.sim.app import PortalSim
from alexia_api.sim.world import (
    DEMO_PASSWORD_A,
    DEMO_PASSWORD_B,
    DEMO_USER_A,
    DEMO_USER_B,
    MUSEUM_FORM_FILE_ID,
    SIM_INSTITUTION_KEY,
    synthetic_guid,
)

DEMO_KEY_NAME: Final = "demo"

ENDING_SIGNALS: Final = tuple(
    signal.Signals[name] for name in ("SIGTERM", "SIGHUP") if name in signal.Signals.__members__
)
"""The signals that ask a process to end. Windows has no hangup signal."""

WILDCARD_HOSTS: Final = frozenset({"0.0.0.0", "::"})  # noqa: S104
"""Host names that mean every network interface, which no browser can open. Nothing binds to
them here. They only decide which address to show."""


@dataclass(frozen=True, slots=True)
class Suggestion:
    """A request the demo suggests, with a few words about it.

    A request that answers with a file says where to save it, because a terminal would show the
    bytes of a file as noise.
    """

    path: str
    what: str
    save_as: str | None = None


_MUSEUM_MESSAGE: Final = f"/v1/accounts/marta/messages/{synthetic_guid(0x1002)}"

TOUR: Final = (
    Suggestion("/v1/accounts", "the accounts this key may use"),
    Suggestion("/v1/accounts/marta/children", "the children of one account"),
    Suggestion(
        "/v1/accounts/marta/children/lucia/tracking", "what the school tracks for one child"
    ),
    Suggestion("/v1/accounts/marta/folders", "the message folders of one account"),
    Suggestion("/v1/accounts/marta/messages?limit=5", "the five newest messages"),
    Suggestion(_MUSEUM_MESSAGE, "one message, with its words, its links and its files"),
    Suggestion(
        f"{_MUSEUM_MESSAGE}/attachments/{attachment_token(MUSEUM_FORM_FILE_ID)}",
        "the file of that message",
        save_as="museo.pdf",
    ),
)
"""Requests the demo suggests. A test asks for each one."""


@dataclass(frozen=True, slots=True)
class Demo:
    app: FastAPI
    key: str
    settings: Settings


@contextmanager
def demo_state() -> Iterator[Path]:
    """A folder for the demo's state, removed when the demo ends.

    A signal that asks a process to end, such as the one `docker stop` sends or the hangup that
    closing a terminal sends, ends it on the spot and would leave the folder behind. While the
    folder exists, those signals become an exit instead, so the folder is removed first. The exit
    status stays the usual 128 plus the signal number.
    """

    def stop(signum: int, _frame: FrameType | None) -> NoReturn:
        raise SystemExit(128 + signum)

    previous = {ending: signal.signal(ending, stop) for ending in ENDING_SIGNALS}
    try:
        with tempfile.TemporaryDirectory(prefix="alexia-demo-") as folder:
            yield Path(folder)
    finally:
        for ending, handler in previous.items():
            signal.signal(ending, handler)


def build_demo(state_dir: Path, clock: Clock | None = None) -> Demo:
    """The server, and a key that may use every account and every scope."""
    sim = PortalSim()
    settings = FixedSettings(
        state_dir=state_dir,
        accounts={
            "marta": AccountSettings(
                portal_url=sim.base_url,
                institution_key=SIM_INSTITUTION_KEY,
                username=SecretStr(DEMO_USER_A),
                password=SecretStr(DEMO_PASSWORD_A),
                label="The family of Marta, made up",
            ),
            "pablo": AccountSettings(
                portal_url=sim.base_url,
                institution_key=SIM_INSTITUTION_KEY,
                username=SecretStr(DEMO_USER_B),
                password=SecretStr(DEMO_PASSWORD_B),
                label="The family of Pablo, made up",
            ),
        },
    )
    registry = Registry.build(
        settings, environ={}, clock=clock, transport_for=lambda _account: sim.transport()
    )
    keys = ApiKeyStore(state_dir / FILE_NAME, clock)
    issued = keys.create(DEMO_KEY_NAME, scopes=["admin"], accounts=[ALL_ACCOUNTS])
    app = create_app(settings, registry=registry, keys=keys, clock=clock)
    return Demo(app=app, key=issued.key, settings=settings)


def address(host: str, port: int) -> str:
    """The web address to open for a server that listens on this host and port."""
    shown = "localhost" if host in WILDCARD_HOSTS else host
    if ":" in shown:
        shown = f"[{shown}]"
    return f"http://{shown}:{port}"


def banner(base: str, key: str, *, windows: bool = False) -> str:
    """What a person needs to start trying the demo, with the key and the address filled in.

    Each address is quoted, because zsh reads an unquoted `?` as a wildcard.
    """
    curl = "curl.exe" if windows else "curl"
    requests = "\n\n".join(
        f'    # {item.what}\n    {curl} -H "Authorization: Bearer {key}" "{base}{item.path}"'
        + (f' --output "{item.save_as}"' if item.save_as else "")
        for item in TOUR
    )
    return (
        "The demo is running against a simulated school. It needs no account and no password.\n"
        "Everything it shows is made up, and everything it changes is thrown away when you stop "
        "it.\n"
        "\n"
        "Your demo key can use every account and every scope.\n"
        "\n"
        f"    {key}\n"
        "\n"
        "To try the API in a browser, open the documentation and press Authorize.\n"
        "\n"
        f"    {base}/docs\n"
        "\n"
        "To try it from a terminal, copy a line.\n"
        "\n"
        f"{requests}\n"
        "\n"
        "Press Ctrl+C to stop."
    )
