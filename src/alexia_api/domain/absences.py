"""Absences and the other attendance incidents that the portal lists for a child."""

from datetime import date

from pydantic import Field

from alexia_api.domain.base import Model
from alexia_api.domain.ids import AbsenceId


class Absence(Model):
    """One attendance incident of a child, such as a missed day or a late arrival.

    The portal lists these on its page for justifying absences. Most are absences, and some are
    other incidents, so `incident` holds the portal's own words for what happened.
    """

    id: AbsenceId = Field(description="The portal's incident id.")
    occurred_on: date = Field(description="The day of the incident, on the school's calendar.")
    hour: str | None = Field(
        description=(
            "What the portal prints in its hour column, as text, for an incident that belongs to "
            "a time of the day. Null for an incident that covers the whole day."
        )
    )
    area: str | None = Field(description="The area or subject the portal files the incident under.")
    teacher: str | None = Field(description="The teacher the portal names for the incident.")
    incident: str = Field(
        description="The portal's own words for what happened, in the school's language."
    )
    note: str | None = Field(description="The note the school wrote about the incident.")
    justifiable: bool = Field(
        description="False when the portal marks the incident as one that cannot be justified."
    )
    justified: bool | None = Field(
        description=(
            "Whether the guardian has justified the incident. Null when the portal's cell is "
            "neither a yes nor a no."
        )
    )
    justification: str | None = Field(
        description="The reason that was given when it was justified."
    )
    accepted: bool | None = Field(
        description=(
            "Whether the school accepted the justification. Null when the portal's cell is "
            "neither a yes nor a no."
        )
    )
