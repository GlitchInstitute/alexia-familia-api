"""Reading the tracking widget, which shows five counters for one child."""

import re

from alexia_api.domain.children import TrackingCounters
from alexia_api.domain.errors import PortalError, SchemaDrift, sample_of
from alexia_api.domain.ids import StudentId
from alexia_api.portal import wire
from alexia_api.portal.allowlist import GET_TRACKING
from alexia_api.portal.session import Tx
from alexia_api.portal.ws import call_ws

_COUNT = re.compile(r"<em[^>]*>\s*([0-9]+)\s*</em>", re.IGNORECASE)


def _count(widget: str, fragment: str) -> int:
    found = _COUNT.search(fragment)
    if found is None:
        raise PortalError(
            SchemaDrift(where=f"tracking widget {widget}", sample=sample_of(fragment))
        )
    return int(found.group(1))


def parse_tracking(reply: wire.TrackingReply) -> TrackingCounters:
    return TrackingCounters(
        tasks=_count("tasks", reply.tasks),
        activities=_count("activities", reply.activities),
        notes=_count("notes", reply.notes),
        tests=_count("tests", reply.tests),
        incidents=_count("incidents", reply.incidents),
    )


async def read_tracking(tx: Tx, student_id: StudentId) -> TrackingCounters:
    reply = await call_ws(tx, GET_TRACKING, wire.TrackingParams(student_id=student_id))
    return parse_tracking(reply)
