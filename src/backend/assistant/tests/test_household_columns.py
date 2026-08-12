"""E04 phase 2: the assistant domain models carry a household.

Two of the five take household without created_by — see the base-class table
in the plan. MemoryEmbedding is machine-derived, and AssistantUsageEvent's
`user` column is already the actor rather than the tenant.
"""

import pytest
from model_bakery import baker

from accounts.models import Household

pytestmark = pytest.mark.django_db


AUTHORED = [
    "assistant.ChatMessage",
    "assistant.MemoryRule",
    "assistant.ReceiptDraft",
]
OWNED_ONLY = [
    "assistant.MemoryEmbedding",
    "assistant.AssistantUsageEvent",
]


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


def _required_extras(label):
    """Fields model_bakery cannot invent for itself.

    pgvector's VectorField has no baker generator, so the embedding has to be
    handed over explicitly — the same 1536 zeros-and-a-bit the existing
    semantic-memory tests use.
    """
    if label == "assistant.MemoryEmbedding":
        return {"embedding": [0.1] * 1536}
    return {}


@pytest.mark.parametrize("label", AUTHORED + OWNED_ONLY)
def test_model_carries_household(label, user):
    from django.apps import apps

    model = apps.get_model(label)
    household = baker.make(Household)
    row = baker.make(model, user=user, household=household, **_required_extras(label))

    assert row.household == household


@pytest.mark.parametrize("label", AUTHORED)
def test_authored_model_records_who_wrote_it(label, user):
    from django.apps import apps

    model = apps.get_model(label)
    row = baker.make(model, user=user, household=baker.make(Household), created_by=user)

    assert row.created_by == user


@pytest.mark.parametrize("label", OWNED_ONLY)
def test_machine_written_model_has_no_created_by(label):
    """Not an oversight — asserted, so nobody 'fixes' it later. An embedding
    has no human author, and a usage event's `user` IS its author."""
    from django.apps import apps

    model = apps.get_model(label)
    field_names = {f.name for f in model._meta.get_fields()}

    assert "household" in field_names
    assert "created_by" not in field_names


@pytest.mark.parametrize("label", AUTHORED + OWNED_ONLY)
def test_model_scopes_through_the_household_manager(label, user):
    from django.apps import apps

    model = apps.get_model(label)
    ours = baker.make(Household)
    theirs = baker.make(Household)
    extras = _required_extras(label)
    baker.make(model, user=user, household=ours, **extras)
    baker.make(model, user=user, household=theirs, **extras)

    assert model.objects.for_household(ours).count() == 1
