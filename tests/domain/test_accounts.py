"""What a block says about itself."""

from datetime import datetime, timedelta, timezone
from typing import get_args

import pytest

from alexia_api.domain.accounts import Blocked
from alexia_api.domain.errors import BREAKER_CAUSE_TEXT, BreakerCause

SCHOOL_TIME = timezone(timedelta(hours=2))


@pytest.mark.parametrize("cause", get_args(BreakerCause))
def test_a_block_says_when_it_began_and_why(cause: BreakerCause) -> None:
    blocked = Blocked(cause=cause, since=datetime(2026, 10, 18, 21, 40, tzinfo=SCHOOL_TIME))

    assert blocked.when_and_why() == (
        f"since 2026-10-18 21:40 +0200 because {BREAKER_CAUSE_TEXT[cause]}"
    )
