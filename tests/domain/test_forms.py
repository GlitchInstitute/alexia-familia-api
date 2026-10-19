"""A form as the list and its page describe it."""

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from alexia_api.domain.forms import Form, FormContent, FormSummary
from alexia_api.domain.ids import FormId
from alexia_api.domain.messages import Body

SUMMARY = FormSummary(
    id=FormId("5afe0000-0000-4000-8000-000000001401"),
    subject="Autorización para la salida al zoo",
    sender="Secretaría",
    received_on=date(2026, 10, 16),
    expires_on=date(2026, 10, 30),
    category="Autorizaciones",
)
BODY = Body(html="<p>Hola</p>", text="Hola", simplified=False)
CONTENT = FormContent(
    sent_at=datetime(2026, 10, 16, 10, 0, tzinfo=timezone(timedelta(hours=2))),
    body=BODY,
    links=(),
    child_names="Lucía",
)


def without(model: FormSummary | FormContent, field: str) -> dict[str, object]:
    return {key: value for key, value in model.model_dump().items() if key != field}


def test_a_form_is_a_row_of_the_list_joined_to_its_page() -> None:
    form = Form.of(SUMMARY, CONTENT)

    assert form.id == SUMMARY.id
    assert form.expires_on == date(2026, 10, 30)
    assert form.category == "Autorizaciones"
    assert form.body == BODY
    assert form.sent_at == CONTENT.sent_at
    assert form.child_names == "Lucía"


def test_the_row_and_the_page_share_no_field_so_neither_can_hide_the_other() -> None:
    assert not set(FormSummary.model_fields) & set(FormContent.model_fields)


def test_the_fields_of_the_row_come_before_the_fields_of_the_page() -> None:
    assert list(Form.model_fields) == [*FormSummary.model_fields, *FormContent.model_fields]


def test_a_form_keeps_the_offset_of_the_school_in_json() -> None:
    assert '"sent_at":"2026-10-16T10:00:00+02:00"' in Form.of(SUMMARY, CONTENT).model_dump_json()


def test_the_time_a_form_was_sent_must_say_its_offset() -> None:
    naive = {**CONTENT.model_dump(), "sent_at": datetime(2026, 10, 16, 10, 0)}

    with pytest.raises(ValidationError, match="sent_at"):
        FormContent.model_validate(naive)


def test_a_form_may_have_no_expiry_no_category_and_no_children() -> None:
    bare = SUMMARY.model_copy(update={"expires_on": None, "category": None})
    unnamed = CONTENT.model_copy(update={"child_names": None})

    form = Form.of(bare, unnamed)

    assert (form.expires_on, form.category, form.child_names) == (None, None, None)


@pytest.mark.parametrize("field", ["expires_on", "category"])
def test_a_row_must_say_that_it_has_no_expiry_or_no_category(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        FormSummary.model_validate(without(SUMMARY, field))


def test_a_page_must_say_that_it_names_no_children() -> None:
    with pytest.raises(ValidationError, match="child_names"):
        FormContent.model_validate(without(CONTENT, "child_names"))


def test_a_form_is_frozen_and_refuses_unknown_fields() -> None:
    form = Form.of(SUMMARY, CONTENT)

    with pytest.raises(ValidationError):
        form.subject = "Otro asunto"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="extra"):
        FormSummary.model_validate({**SUMMARY.model_dump(), "extra": 1})
