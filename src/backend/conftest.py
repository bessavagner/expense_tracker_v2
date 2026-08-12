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
from model_bakery import baker

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


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


@pytest.fixture
def other_user(db):
    """A second tenant, for asserting that a query stays scoped to one owner."""
    return baker.make("core.CustomUser", username="amanda")


@pytest.fixture
def household(user):
    """The household the `user` fixture writes into.

    Requested eagerly by anything that exercises a household-scoped read: the
    middleware resolves `request.household` from a Membership, and a user
    without one makes every scoped queryset return none().
    """
    from accounts.resolution import household_for_user

    return household_for_user(user)


@pytest.fixture
def other_household(other_user):
    """A second tenant, for asserting a query stays inside one household."""
    from accounts.resolution import household_for_user

    return household_for_user(other_user)
