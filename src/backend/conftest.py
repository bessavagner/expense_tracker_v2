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
    # The address is pinned rather than left to model-bakery. From E05 the
    # email is unique and required, and bakery's random filler is only
    # *usually* distinct — "usually" is how a suite becomes flaky.
    return baker.make("core.CustomUser", username="vagner", email="vagner@example.com")


@pytest.fixture
def other_user(db):
    """A second tenant, for asserting that a query stays scoped to one owner."""
    return baker.make("core.CustomUser", username="amanda", email="amanda@example.com")


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


@pytest.fixture
def logged_client(user, household):
    """A logged-in client whose user resolves to a household.

    `household` is requested for its side effect, and that is the whole point:
    the middleware reads `request.household` from a Membership, and a user
    without one makes every scoped queryset return none() — which would turn
    "the neighbour's row is absent" into a test that passes because *everything*
    is absent. Nine test modules used to shadow this with their own copy that
    omitted the dependency; keeping one definition here is what stops that
    coming back.
    """
    from django.test import Client

    client = Client()
    client.force_login(user)
    return client
