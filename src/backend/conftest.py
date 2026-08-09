"""Suite-wide fixtures.

``TEST_CLOCK_SHIFT`` moves the whole suite's clock so that wall-clock dependence
surfaces on demand — in a nightly job, or in one command before a release —
instead of on a random future morning. See ``docs/testing-conventions.md``.

    TEST_CLOCK_SHIFT=+1y POSTGRES_PORT=5433 uv run pytest src/backend/ -q
"""

import os
from datetime import UTC, datetime

import pytest
import time_machine

from core.clock import parse_shift


@pytest.fixture(autouse=True)
def shifted_clock():
    """Shift the clock for every test when TEST_CLOCK_SHIFT is set.

    ``tick=True`` so time still advances inside a test — freezing the whole
    suite would break anything that relies on two timestamps differing.
    Per-test ``time_machine.move_to`` calls nest inside this and win, which is
    what a test that pins its own date expects.
    """
    raw = os.environ.get("TEST_CLOCK_SHIFT")
    if not raw:
        yield
        return
    destination = datetime.now(UTC) + parse_shift(raw)
    with time_machine.travel(destination, tick=True):
        yield
