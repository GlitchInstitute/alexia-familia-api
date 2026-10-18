"""The `alexia-api accounts` commands. They show the accounts and lift a pause on a login."""

from typing import Annotated

import typer

from alexia_api.cli.shared import ConfigOption, fail, load, make_app, table, words
from alexia_api.domain.ids import parse_account_id
from alexia_api.oserrors import why
from alexia_api.portal.breaker import BREAKER_DIRECTORY, BreakerStore

app = make_app("accounts", "Show the accounts and lift the pause on a login.")


@app.command("list")
def list_accounts(config: ConfigOption = None) -> None:
    """List the accounts and whether the server may log in to each one.

    The server pauses logins to an account after a failure that could lock it at the school, such
    as a wrong password. The list shows which accounts are paused and why.
    """
    settings = load(config)
    if not settings.accounts:
        typer.echo(
            "There are no accounts. Add one to the configuration file, "
            "or run `alexia-api init` to write a starter file."
        )
        return
    breakers = BreakerStore(settings.state_dir / BREAKER_DIRECTORY)
    rows: list[tuple[str, str, str]] = []
    for name, account in settings.accounts.items():
        blocked = breakers.read(parse_account_id(name))
        logins = "allowed" if blocked is None else f"paused {blocked.when_and_why()}"
        rows.append((name, account.portal_host, logins))
    typer.echo(table(("ACCOUNT", "PORTAL", "LOGINS"), rows))


@app.command()
def reset(
    name: Annotated[
        str,
        typer.Argument(metavar="NAME", help="The account, as the configuration file names it."),
    ],
    config: ConfigOption = None,
) -> None:
    """Lift the pause on the logins to an account.

    The server stops logging in to an account after a failure that could lock it at the school,
    such as a wrong password, and it waits for a person to lift the pause. Fix the cause first.
    A reset allows one more try, and a wrong password can lock the account. A running server
    follows the reset at once.
    """
    settings = load(config)
    if name not in settings.accounts:
        known = (
            f"the accounts are {words(list(settings.accounts))}"
            if settings.accounts
            else "there are no accounts"
        )
        fail(f"no account is named {name}, {known}")
    breakers = BreakerStore(settings.state_dir / BREAKER_DIRECTORY)
    account = parse_account_id(name)
    blocked = breakers.read(account)
    if blocked is None:
        typer.echo(f"Logins to {name} are not paused. There is nothing to reset.")
        return
    try:
        breakers.clear(account)
    except OSError as error:
        fail(f"the pause on {name} cannot be lifted, {why(error)}")
    typer.echo(
        f"Lifted the pause on {name}. Logins had been paused {blocked.when_and_why()}. "
        "The server tries to log in at the next request that needs the portal. "
        "If the cause is not fixed, the pause comes back after that one try."
    )
