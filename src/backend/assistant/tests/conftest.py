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
