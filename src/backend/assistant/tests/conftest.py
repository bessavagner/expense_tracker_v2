import os

import pydantic_ai.models
import pytest
from django.test import Client
from model_bakery import baker

# Só libera chamadas reais de modelo quando RUN_LLM_TESTS=1 (testes de LLM
# real, normalmente pulados — ver test_image_extraction_regression.py).
pydantic_ai.models.ALLOW_MODEL_REQUESTS = os.environ.get("RUN_LLM_TESTS") == "1"


# `user`, `other_user`, `household` and `other_household` live in the root
# `src/backend/conftest.py` — one definition, reachable from every app's tests.


@pytest.fixture
def logged_client(user, household):
    """A logged-in client whose user resolves to a household.

    `household` is requested for its side effect: the middleware reads
    `request.household` from a Membership, and a user without one makes every
    scoped queryset return none() — which would turn "the neighbour's row is
    absent" assertions into vacuous passes.
    """
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def seeded_user(user):
    """User with categories and payment methods for agent testing."""
    baker.make("finances.Category", user=user, name="Alimentação")
    baker.make("finances.Category", user=user, name="Lanche")
    baker.make("finances.Category", user=user, name="Álcool")
    baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    baker.make(
        "finances.PaymentMethod",
        user=user,
        name="Crédito C6",
        type="credit_card",
        closing_day=25,
    )
    return user
