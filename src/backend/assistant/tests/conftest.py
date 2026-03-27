import pydantic_ai.models
import pytest
from django.test import Client
from model_bakery import baker

pydantic_ai.models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


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
