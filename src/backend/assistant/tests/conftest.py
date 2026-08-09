import os

import pydantic_ai.models
import pytest
from django.test import Client
from model_bakery import baker

# Só libera chamadas reais de modelo quando RUN_LLM_TESTS=1 (testes de LLM
# real, normalmente pulados — ver test_image_extraction_regression.py).
pydantic_ai.models.ALLOW_MODEL_REQUESTS = os.environ.get("RUN_LLM_TESTS") == "1"


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


@pytest.fixture
def other_user(db):
    """A second tenant, for asserting that a query stays scoped to one user."""
    return baker.make("core.CustomUser", username="amanda")


@pytest.fixture
def logged_client(user):
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
