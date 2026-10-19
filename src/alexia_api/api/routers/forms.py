"""The forms that the school asks a guardian to answer, such as authorizations and surveys."""

from typing import Annotated

from fastapi import APIRouter, Path, Response

from alexia_api.api.errors import problem_responses
from alexia_api.api.params import CACHE_HEADERS, FreshQuery, ReadAccount, stamp
from alexia_api.api.schemas import FormList
from alexia_api.domain.forms import Form

router = APIRouter(
    prefix="/v1/accounts/{account}/forms",
    tags=["forms"],
    responses=problem_responses(401, 403, 404, 429, 500, 502, 503, 504),
)

FormPath = Annotated[
    str,
    Path(description="The form's id, as the list of forms shows it. Letter case does not matter."),
]


@router.get(
    "",
    summary="List the forms of an account",
    description=(
        "Needs the `read` scope. These are the forms that the school asks the guardian to "
        "answer, such as an authorization or a survey, newest first. The portal belongs to the "
        "guardian and not to a child, so the list holds the forms for every child of the "
        "account. This server only reads them. It does not read the questions of a form and "
        "it cannot tell whether a form was answered, so a guardian answers in the portal "
        "itself. The portal shows the forms and the messages in the same place, so a read "
        "switches its list to the forms and back, and a read that fails in between ends the "
        "session, which costs one more login. No real list of forms has been read while "
        "building this route. The server checks that the portal's page says that it lists "
        "forms, and a page that does not fails with `unexpected_reply`. A list that is shaped "
        "in a way the server does not know fails with `portal_changed`."
    ),
    responses=CACHE_HEADERS,
)
async def list_forms(
    account: ReadAccount, response: Response, fresh: FreshQuery = False
) -> FormList:
    listing = await account.forms(fresh=fresh)
    stamp(response, listing)
    return FormList(items=listing.value.forms, truncated=listing.value.truncated)


@router.get(
    "/{form}",
    summary="Read one form",
    description=(
        "Needs the `read` scope. Gives the form as the list shows it, together with when the "
        "school sent it and its words. `body.html` is safe to show, and `body.text` holds the "
        "same words as plain text. The form must be in the list of forms. The server stores a "
        "form after it reads it, so asking again is cheap. `fresh=true` reads the form again, "
        "and the list too. Opening a form in the portal may mark it as read there, and this "
        "server cannot tell whether it does. Files that came with a form are not served."
    ),
    responses=CACHE_HEADERS,
)
async def get_form(
    account: ReadAccount, form: FormPath, response: Response, fresh: FreshQuery = False
) -> Form:
    found = await account.form(form, fresh=fresh)
    stamp(response, found)
    return found.value
