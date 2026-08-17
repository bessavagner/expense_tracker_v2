import os

import pydantic_ai.models
import pytest
from model_bakery import baker

# Só libera chamadas reais de modelo quando RUN_LLM_TESTS=1 (testes de LLM
# real, normalmente pulados — ver test_image_extraction_regression.py).
pydantic_ai.models.ALLOW_MODEL_REQUESTS = os.environ.get("RUN_LLM_TESTS") == "1"


# `user`, `other_user`, `household`, `other_household` and `logged_client` all
# live in the root `src/backend/conftest.py` — one definition, reachable from
# every app's tests. Do not shadow `logged_client` here: a copy that omits the
# `household` dependency makes household-scoped view tests pass vacuously.


@pytest.fixture
def scope(user, household):
    """What the agent is allowed to see, and who is asking.

    Every tool and every analytics function takes one of these; building it
    here keeps the tests honest about where scope comes from — deps, never a
    tool argument.
    """
    from assistant.agents.scope import AgentScope

    return AgentScope(household=household, user=user)


@pytest.fixture
def other_scope(other_user, other_household):
    """The neighbour's scope, for asserting a tool cannot reach across."""
    from assistant.agents.scope import AgentScope

    return AgentScope(household=other_household, user=other_user)


@pytest.fixture
def seeded_user(user, household):
    """User with categories and payment methods for agent testing."""
    baker.make("finances.Category", household=household, name="Alimentação")
    baker.make("finances.Category", household=household, name="Lanche")
    baker.make("finances.Category", household=household, name="Álcool")
    baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    baker.make(
        "finances.PaymentMethod",
        household=household,
        name="Crédito C6",
        type="credit_card",
        closing_day=25,
    )
    return user


@pytest.fixture
def seeded_scope(seeded_user, scope):
    """`scope`, with the catalogue `seeded_user` creates already in place."""
    return scope


@pytest.fixture
def interaction(db, household, user):
    """One admitted user action, for correlating UsageRecord rows against."""
    from assistant.models import InteractionKind, UsageInteraction

    return UsageInteraction.objects.create(
        household=household, user=user, kind=InteractionKind.TEXT
    )


@pytest.fixture
def plan(db):
    """The seeded beta plan every household falls back to."""
    from accounts.models import Plan

    return Plan.objects.get(is_default=True)


@pytest.fixture
def household_mate(db, household):
    """A second member of the SAME household.

    Distinct from the root `other_user` fixture, which is a second *tenant*.
    Two facts need proving at once and they point opposite ways: credits are
    the household's shared pool, while the abuse ceiling counts the person.
    """
    from model_bakery import baker

    from accounts.models import Membership

    u = baker.make("core.CustomUser", username="colega", email="colega@example.com")
    Membership.objects.create(user=u, household=household)
    return u


@pytest.fixture
def consented_user(user):
    """A user who has authorised the AI processing (E13).

    Most of this suite is about what the assistant *does*, not about whether it
    is allowed to. Without this, every one of those tests would assert a 403
    from the consent gate and prove nothing about the behaviour it names.

    A test that is actually about the gate asks for `user` and sets consent
    itself — see `test_ai_consent_gate.py`.
    """
    from core.privacy import set_ai_consent

    set_ai_consent(user, granted=True)
    return user
