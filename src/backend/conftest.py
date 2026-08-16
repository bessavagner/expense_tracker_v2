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


@pytest.fixture(autouse=True)
def isolated_job_storage(tmp_path, settings):
    """Every test's import uploads and export archives go to its own tmp_path.

    Two reasons this is autouse rather than opt-in (E12). Without it a test
    that uploads a CSV writes into ``BASE_DIR/.jobstore`` — the developer's
    real working tree — and leaves it there, so the suite's tenth run has
    nine files of somebody's ledger lying in the repo. And a test that forgets
    to unset ``GS_BUCKET_NAME`` would reach for a real bucket, which is the
    one thing "local development works without GCP credentials" must never
    do by accident.
    """
    settings.GS_BUCKET_NAME = ""
    settings.JOB_STORAGE_ROOT = tmp_path / "jobstore"
    return settings.JOB_STORAGE_ROOT


@pytest.fixture(autouse=True)
def clean_cache():
    """Empty the cache between tests.

    The database is rolled back per test; the cache is not, and from E05 there
    is rate-limiting state in it (allauth keys its throttles by IP and by
    login). Without this, a module's second test inherits the first one's
    counters and fails only when run alongside its neighbours — the worst
    possible failure to debug, because it passes in isolation.
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def no_real_embedding_calls():
    """Stop the suite from paying OpenAI for embeddings.

    ``pydantic_ai.models.ALLOW_MODEL_REQUESTS = False`` guards the *agent*
    calls, but the embedding and transcription services talk to the OpenAI SDK
    directly and are not covered by it. `TestModel` calls every tool it is
    given, `check_memory` is one of them, and it reaches `get_embedding` — so
    until E07 made these calls visible in `UsageRecord`, every image and chat
    test was quietly billing a real embeddings request against
    `OPENAI_API_KEY`.

    Same opt-in as the agent guard: ``RUN_LLM_TESTS=1`` lets the real calls
    through. A test that wants a fake response patches this same attribute and
    wins, because the patch replaces the object rather than wrapping it.
    """
    if os.environ.get("RUN_LLM_TESTS") == "1":
        yield
        return

    from types import SimpleNamespace
    from unittest import mock

    async def refuse(*args, **kwargs):
        raise RuntimeError(
            "Real embedding request in a test. Patch "
            "`assistant.services.embedding.async_client`, or set RUN_LLM_TESTS=1."
        )

    stub = SimpleNamespace(embeddings=SimpleNamespace(create=refuse))
    with mock.patch("assistant.services.embedding.async_client", stub):
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
    """The household the `user` fixture writes into — already onboarded.

    Onboarded by default because that is the product's ordinary state, and
    because from E11 a household that has not finished the guided setup is
    redirected out of every page. Without this, "the neighbour's row is absent"
    would become a test that passes because *every* page is a 302.

    A test about the new-household path asks for `new_household`, or deletes
    the `OnboardingState` row itself.
    """
    from accounts.models import OnboardingState, OnboardingStep
    from accounts.resolution import household_for_user

    resolved = household_for_user(user)
    state = OnboardingState.for_household(resolved)
    for step in OnboardingStep:
        state.mark(step)
    return resolved


@pytest.fixture
def other_household(other_user):
    """A second tenant, for asserting a query stays inside one household."""
    from accounts.models import OnboardingState, OnboardingStep
    from accounts.resolution import household_for_user

    resolved = household_for_user(other_user)
    state = OnboardingState.for_household(resolved)
    for step in OnboardingStep:
        state.mark(step)
    return resolved


def complete_onboarding(household):
    """Mark `household`'s guided setup complete; returns it for chaining.

    The `household`/`other_household` fixtures above already arrive onboarded.
    This is for tests that build a household directly — most often via
    `accounts.resolution.household_for_user` in a `TestCase.setUp`, which does
    not go through either fixture — so from E11 they would otherwise be
    redirected to `/casa/comecar/` on every request.
    """
    from accounts.models import OnboardingState, OnboardingStep

    state = OnboardingState.for_household(household)
    for step in OnboardingStep:
        state.mark(step)
    return household


@pytest.fixture
def new_household(user):
    """A household that has NOT been through the guided setup.

    For tests that are actually about onboarding. Deliberately not the default:
    a test that gets the new-household path by accident fails in a way that
    looks like a routing bug.
    """
    from accounts.resolution import household_for_user

    return household_for_user(user)


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
