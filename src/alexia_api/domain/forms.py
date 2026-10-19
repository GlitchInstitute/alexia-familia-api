"""Forms that the school asks a guardian to answer, such as an authorization or a survey.

The portal lists a form like a message, in its own list, and it opens the form on the page of a
message. This server reads the list and the words of a form. It does not read the questions or
the answers, and it cannot tell whether a form was answered.
"""

from datetime import date
from typing import Self

from pydantic import AwareDatetime, Field

from alexia_api.domain.base import Model
from alexia_api.domain.ids import FormId
from alexia_api.domain.messages import Body, Link


class FormSummary(Model):
    """A form as the portal lists it, without its words."""

    id: FormId = Field(description="The portal's form id. The detail route takes it.")
    subject: str = Field(description="The subject line, which says what the school asks for.")
    sender: str = Field(description="The sender's name as the portal shows it.")
    received_on: date = Field(
        description="The day the portal lists the form under, on the school's calendar."
    )
    expires_on: date | None = Field(
        description="The last day the portal shows the form, when it has one."
    )
    category: str | None = Field(description="The category the portal files the form under.")


class FormContent(Model):
    """What the page of a form adds to its row in the list."""

    sent_at: AwareDatetime = Field(
        description=(
            "When the school sent the form, to the minute, with the school's offset. The list "
            "gives only a day, and the time comes from the form itself."
        )
    )
    body: Body = Field(description="The words of the form.")
    links: tuple[Link, ...] = Field(
        description="The addresses in the body, each once. The ones in links come first."
    )
    child_names: str | None = Field(
        description=(
            "The names of the children the portal says the form is about, in the one text the "
            "portal writes them in, or null when it names none. The portal gives names and no "
            "ids, so this API cannot tie them to its list of children."
        )
    )


class Form(FormContent, FormSummary):
    """A form with its words. The fields of its row in the list come first."""

    @classmethod
    def of(cls, summary: FormSummary, content: FormContent) -> Self:
        """Join a row of the list to the page that the row opens."""
        return cls(**dict(summary), **dict(content))
