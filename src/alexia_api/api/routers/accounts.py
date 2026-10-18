"""Accounts, and the state of each one's connection to the portal."""

from typing import Annotated

from fastapi import APIRouter, Depends

from alexia_api.api.auth import require
from alexia_api.api.deps import ServicesDep
from alexia_api.api.errors import problem_responses
from alexia_api.api.params import AdminAccount, ReadAccount
from alexia_api.api.schemas import AccountList, ConnectionCheck, ConnectionReset
from alexia_api.domain.accounts import Account
from alexia_api.domain.security import Principal

router = APIRouter(
    prefix="/v1/accounts",
    tags=["accounts"],
    responses=problem_responses(401, 403, 429, 500),
)


@router.get(
    "",
    summary="List the accounts this key may use",
    description=(
        "Needs the `read` scope. It lists the accounts the key is allowed to use, with the "
        "state of each connection. It never calls the portal, so it is cheap and safe to poll."
    ),
)
async def list_accounts(
    principal: Annotated[Principal, Depends(require("read"))], services: ServicesDep
) -> AccountList:
    runtimes = services.registry.visible_to(principal)
    return AccountList(items=tuple([await runtime.status() for runtime in runtimes]))


@router.get(
    "/{account}",
    summary="Show one account",
    description=(
        "Needs the `read` scope. It shows the state of the connection, which switches the "
        "operator turned on, and how many children the last login listed. It never calls "
        "the portal."
    ),
    responses=problem_responses(404),
)
async def get_account(account: ReadAccount) -> Account:
    return await account.status()


@router.post(
    "/{account}/connection/check",
    summary="Make sure the account has a working portal session",
    description=(
        "Needs the `read` scope. It uses the session the server has when that still works, "
        "and logs in when it does not. A login failure that could lock the account pauses "
        "automatic logins until an operator resets the block. Use this to test new credentials."
    ),
    responses=problem_responses(404, 502, 503, 504),
)
async def check_connection(account: ReadAccount) -> ConnectionCheck:
    result = await account.check()
    return ConnectionCheck(session=result.session, child_count=result.child_count)


@router.post(
    "/{account}/connection/reset",
    summary="Lift a block on automatic logins",
    description=(
        "Needs the `admin` scope. Run this only after you fixed the cause, which means "
        "correcting the password or finishing a step in the portal in a browser. The next request "
        "that needs the portal logs in again."
    ),
    responses=problem_responses(404),
)
async def reset_connection(account: AdminAccount) -> ConnectionReset:
    return ConnectionReset(was_blocked=await account.reset_block())
