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
def seeded_user(user, household):
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
