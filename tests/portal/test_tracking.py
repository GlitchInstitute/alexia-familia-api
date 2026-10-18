"""Reading the tracking counters for a child."""

import pytest

from alexia_api.domain.children import TrackingCounters
from alexia_api.domain.errors import PortalError, SchemaDrift, WsRejected
from alexia_api.domain.ids import parse_student_id
from alexia_api.portal import wire
from alexia_api.portal.allowlist import GET_TRACKING
from alexia_api.portal.tracking import parse_tracking, read_tracking
from alexia_api.sim.world import default_world
from tests.harness import Failure, Harness

REPLY = wire.TrackingReply(
    tasks='<div><em class="n"> 12 </em></div>',
    activities="<em>0</em>",
    notes="<span><EM>3</EM></span>",
    tests="<em>7</em> tests",
    incidents="<em>1</em>",
)
WIDGETS = ["tasks", "activities", "notes", "tests", "incidents"]


def test_reads_each_counter_from_its_fragment() -> None:
    assert parse_tracking(REPLY) == TrackingCounters(
        tasks=12, activities=0, notes=3, tests=7, incidents=1
    )


@pytest.mark.parametrize("widget", WIDGETS)
@pytest.mark.parametrize("fragment", ["<p>nothing</p>", "<em>many</em>", "", "<em></em>"])
def test_a_fragment_without_a_number_is_schema_drift(widget: str, fragment: str) -> None:
    broken = REPLY.model_copy(update={widget: fragment})

    with pytest.raises(PortalError) as raised:
        parse_tracking(broken)

    detail = raised.value.detail
    assert isinstance(detail, SchemaDrift)
    assert detail.where == f"tracking widget {widget}"
    assert detail.sample == fragment


@pytest.mark.parametrize(("family_index", "child_index"), [(0, 0), (0, 1), (1, 0), (1, 1)])
async def test_reads_the_counters_the_portal_holds_for_each_child(
    harness: Harness, family_index: int, child_index: int
) -> None:
    family = default_world().families[family_index]
    child = family.children[child_index]
    gateway = harness.gateway(credentials=harness.credentials(family.username, family.password))

    counters = await gateway.call(lambda tx: read_tracking(tx, parse_student_id(child.student_id)))

    expected = child.tracking
    assert counters == TrackingCounters(
        tasks=expected.tasks,
        activities=expected.activities,
        notes=expected.notes,
        tests=expected.tests,
        incidents=expected.incidents,
    )


async def test_a_child_of_another_family_is_rejected_by_the_portal(
    harness: Harness, failure: Failure
) -> None:
    other = default_world().families[1].children[0]
    gateway = harness.gateway()

    detail = await failure(
        gateway.call(lambda tx: read_tracking(tx, parse_student_id(other.student_id)))
    )

    assert detail == WsRejected(call=GET_TRACKING.name, status=500)
