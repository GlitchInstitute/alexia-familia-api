"""The `alexia-api keys` commands. They write the file that a running server rereads."""

from enum import StrEnum
from typing import Annotated

import typer

from alexia_api.cli.shared import ConfigOption, fail, load, make_app, table, words
from alexia_api.domain.security import ALL_ACCOUNTS
from alexia_api.services.keys import FILE_NAME, ApiKeyRecord, ApiKeyStore, KeyStoreError

app = make_app("keys", "Make, list, and revoke the API keys that may call the server.")


class ScopeName(StrEnum):
    """The scopes a key can hold, in the words the command line takes."""

    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
    FEED = "feed"


@app.command()
def create(
    name: Annotated[
        str,
        typer.Argument(
            metavar="NAME",
            help=(
                "A name that tells this key from the others. It appears in logs. Use lower case "
                "letters, digits, and hyphens."
            ),
        ),
    ],
    scope: Annotated[
        list[ScopeName] | None,
        typer.Option(
            "--scope",
            "-s",
            help=(
                "What the key may do. Give the option once for each scope, or leave it out for "
                "read. A read key sees everything the portal shows. A write key also changes "
                "things at the school. An admin key also lifts a block on an account. A feed key "
                "only opens calendar feeds, so it may travel in a URL. A stronger scope includes "
                "the weaker ones."
            ),
        ),
    ] = None,
    account: Annotated[
        list[str] | None,
        typer.Option(
            "--account",
            "-a",
            help=(
                "An account the key may use. Give the option once for each account, or leave it "
                "out for every account."
            ),
        ),
    ] = None,
    config: ConfigOption = None,
) -> None:
    """Make a key and show it once.

    The key goes to standard output and nothing else does, so a script can capture it. The
    server keeps only a hash of the key and cannot show it again. A running server accepts the
    new key at once.
    """
    settings = load(config)
    try:
        issued = ApiKeyStore(settings.state_dir / FILE_NAME).create(
            name,
            scopes=[item.value for item in scope or [ScopeName.READ]],
            accounts=account or [ALL_ACCOUNTS],
        )
    except KeyStoreError as error:
        fail(str(error))
    typer.echo(_made(issued.record), err=True)
    unknown = set(issued.record.accounts) - {ALL_ACCOUNTS} - set(settings.accounts)
    for missing in sorted(unknown):
        typer.echo(f"Note: no account named {missing} is configured yet.", err=True)
    typer.echo("Copy it now. It is shown once, and the server keeps only a hash of it.", err=True)
    typer.echo(issued.key)


@app.command("list")
def list_keys(config: ConfigOption = None) -> None:
    """List the keys by name. The keys themselves are never shown."""
    try:
        records = ApiKeyStore(load(config).state_dir / FILE_NAME).records()
    except KeyStoreError as error:
        fail(str(error))
    if not records:
        typer.echo("There are no keys. Make one with `alexia-api keys create NAME`.")
        return
    rows = [
        (
            record.name,
            ",".join(record.scopes),
            ",".join(record.accounts),
            record.created_at.date().isoformat(),
        )
        for record in records
    ]
    typer.echo(table(("NAME", "SCOPES", "ACCOUNTS", "CREATED"), rows))


@app.command()
def revoke(
    name: Annotated[str, typer.Argument(metavar="NAME", help="The name of the key to revoke.")],
    config: ConfigOption = None,
) -> None:
    """Revoke a key. A running server stops accepting it at once."""
    store = ApiKeyStore(load(config).state_dir / FILE_NAME)
    try:
        revoked = store.revoke(name)
        remaining = [record.name for record in store.records()]
    except KeyStoreError as error:
        fail(str(error))
    if not revoked:
        known = f"the keys are {words(remaining)}" if remaining else "there are no keys"
        fail(f"no key is named {name}, {known}")
    typer.echo(f"Revoked the key {name}. A running server stops accepting it at once.")


def _made(record: ApiKeyRecord) -> str:
    scopes = f"{'scope' if len(record.scopes) == 1 else 'scopes'} {words(record.scopes)}"
    if record.accounts == [ALL_ACCOUNTS]:
        where = "all accounts"
    else:
        noun = "account" if len(record.accounts) == 1 else "accounts"
        where = f"the {noun} {words(record.accounts)}"
    return f"Made the key {record.name} with the {scopes}, for {where}."
