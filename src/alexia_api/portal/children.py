"""Reading the home page, which lists the guardian and the children."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from alexia_api.domain.children import Child, Guardian, assign_slugs
from alexia_api.domain.errors import PortalError, UnexpectedReply
from alexia_api.domain.ids import (
    InvalidIdError,
    PersonId,
    StudentId,
    parse_person_id,
    parse_student_id,
)
from alexia_api.portal.pages import PAGE_ACCEPT, PageRequest, get_page
from alexia_api.portal.session import Tx
from alexia_api.portal.ws import HOME_PATH

_CLICKED = re.compile(r"HijoClicked\(this,\s*'([^']+)'\s*,\s*'(True|False)'\)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class HomeSnapshot:
    guardian: Guardian | None
    children: tuple[Child, ...]


@dataclass(frozen=True, slots=True)
class _PickerEntry:
    person_id: PersonId
    is_guardian: bool
    first_name: str
    relation: str | None


def _text(node: LexborNode | None) -> str:
    return " ".join(node.text().split()) if node is not None else ""


def _person_id(value: str | None) -> PersonId | None:
    if value is None:
        return None
    try:
        return parse_person_id(value)
    except InvalidIdError:
        return None


def _student_id(value: str | None) -> StudentId | None:
    if value is None:
        return None
    try:
        return parse_student_id(value)
    except InvalidIdError:
        return None


def _picker(tree: LexborHTMLParser) -> list[_PickerEntry]:
    entries: list[_PickerEntry] = []
    for item in tree.css("ul.lista_users li[onclick]"):
        clicked = _CLICKED.search(item.attributes.get("onclick") or "")
        person_id = _person_id(clicked.group(1) if clicked else None)
        if clicked is None or person_id is None:
            continue
        entries.append(
            _PickerEntry(
                person_id=person_id,
                is_guardian=clicked.group(2).lower() == "true",
                first_name=_text(item.css_first("h3")),
                relation=_text(item.css_first("strong")) or None,
            )
        )
    return entries


def parse_home(html: str) -> HomeSnapshot:
    """Read the guardian and the children from the home page.

    The page lists people twice. A switcher names each person and says whether they are the
    guardian. A second list shows the children with the student id and a photo whose address
    carries the person id. The two lists are joined on the person id.
    """
    tree = LexborHTMLParser(html)
    picker = _picker(tree)

    found: list[tuple[StudentId, PersonId, str]] = []
    for item in tree.css("ul.lienzo_hijos li[hijo]"):
        student_id = _student_id(item.attributes.get("hijo"))
        image = item.css_first("img")
        photo = (image.attributes.get("src") if image is not None else None) or ""
        key = parse_qs(urlsplit(photo).query).get("key", [None])[0]
        person_id = _person_id(key)
        if student_id is not None and person_id is not None:
            found.append((student_id, person_id, _text(item.css_first("p"))))

    by_person: dict[PersonId, _PickerEntry] = {}
    for candidate in picker:
        if not candidate.is_guardian:
            by_person.setdefault(candidate.person_id, candidate)

    first_names: dict[StudentId, str] = {}
    entries: dict[StudentId, _PickerEntry | None] = {}
    for student_id, person_id, full_name in found:
        entry = by_person.get(person_id)
        entries[student_id] = entry
        first_names[student_id] = (entry.first_name if entry else "") or (
            full_name.split() or [""]
        )[0]

    slugs = assign_slugs(list(first_names.items()))
    children = tuple(
        Child(
            id=student_id,
            person_id=person_id,
            slug=slugs[student_id],
            name=full_name,
            first_name=first_names[student_id],
            relation=entry.relation if (entry := entries[student_id]) else None,
        )
        for student_id, person_id, full_name in found
    )

    guardian_entry = next((entry for entry in picker if entry.is_guardian), None)
    if not children and guardian_entry is None:
        raise PortalError(UnexpectedReply(where="home: no child or guardian switcher"))
    guardian = (
        Guardian(person_id=guardian_entry.person_id, first_name=guardian_entry.first_name)
        if guardian_entry
        else None
    )
    return HomeSnapshot(guardian=guardian, children=children)


async def read_home(tx: Tx) -> HomeSnapshot:
    response = await get_page(
        tx,
        PageRequest(
            name="home",
            path=HOME_PATH,
            referer=tx.absolute(HOME_PATH),
            accept=PAGE_ACCEPT,
        ),
    )
    return parse_home(response.text())
