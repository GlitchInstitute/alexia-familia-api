"""A guardian, their children, and what the portal shows about each child."""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Final

from pydantic import Field

from alexia_api.domain.base import Model
from alexia_api.domain.ids import MAX_SLUG_LENGTH, ChildSlug, PersonId, StaffId, StudentId

_FALLBACK_SLUG: Final = "child"
_SUFFIX_ROOM: Final = 4


class Guardian(Model):
    """The parent or guardian who is signed in."""

    person_id: PersonId = Field(description="The portal's person id for the guardian.")
    first_name: str


class Child(Model):
    """One child of the signed-in guardian."""

    id: StudentId = Field(
        description="The portal's student id. Most per-child calls use it, and so do URLs."
    )
    person_id: PersonId = Field(
        description="The portal's person id for the child. The agenda and the photo use it."
    )
    slug: ChildSlug = Field(
        description="A short name for URLs, made from the first name. The operator can pin it."
    )
    name: str = Field(description="The full name as the portal shows it.")
    first_name: str
    relation: str | None = Field(
        description="How the portal labels the relation to the guardian, when it shows one."
    )


class TrackingCounters(Model):
    """The numbers in the portal's tracking widget for one child."""

    tasks: int = Field(ge=0, description="Homework and tasks.")
    activities: int = Field(ge=0, description="Activities.")
    notes: int = Field(ge=0, description="Teacher notes.")
    tests: int = Field(ge=0, description="Tests and quizzes.")
    incidents: int = Field(ge=0, description="Attendance incidents.")


class StaffMember(Model):
    """A teacher or other staff member who can meet with the guardian about a child."""

    id: StaffId = Field(description="The portal's employee id. Meeting requests use it.")
    name: str
    role: str | None = Field(description="The role the portal prints after the name, if any.")


def slugify(text: str) -> str:
    """Fold a name to lower case ASCII words joined by hyphens, or `child` when nothing is left."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    words = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return words[: MAX_SLUG_LENGTH - _SUFFIX_ROOM].strip("-") or _FALLBACK_SLUG


def assign_slugs(
    children: Sequence[tuple[StudentId, str]],
    pinned: Mapping[StudentId, ChildSlug] | None = None,
) -> dict[StudentId, ChildSlug]:
    """Give each child a slug from the first name, adding `-2`, `-3` on a collision.

    A pinned slug is kept as given, and the other children work around it. A pin for a child that
    the portal no longer lists is ignored, which frees its slug.

    Children are ranked by student id before slugs are handed out, so the answer does not depend
    on the order the portal lists them in. The child with the smallest id keeps the plain slug.
    """
    listed = {student_id for student_id, _ in children}
    slugs = {
        student_id: slug for student_id, slug in (pinned or {}).items() if student_id in listed
    }
    taken: set[str] = set(slugs.values())
    if len(taken) != len(slugs):
        raise ValueError("two children are pinned to the same slug")
    for student_id, first_name in sorted(children, key=lambda entry: entry[0]):
        if student_id in slugs:
            continue
        base = slugify(first_name)
        candidate = base
        number = 2
        while candidate in taken:
            candidate = f"{base}-{number}"
            number += 1
        taken.add(candidate)
        slugs[student_id] = ChildSlug(candidate)
    return slugs


def apply_pins(
    children: Sequence[Child], pinned: Mapping[StudentId, ChildSlug]
) -> tuple[Child, ...]:
    """Return the children with their final slugs, in the order given."""
    slugs = assign_slugs([(child.id, child.first_name) for child in children], pinned)
    return tuple(child.model_copy(update={"slug": slugs[child.id]}) for child in children)
