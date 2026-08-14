"""E04 phase 2: the assistant domain models carry a household.

Two of the five take household without created_by — see the base-class table
in the plan. MemoryEmbedding is machine-derived, and UsageInteraction's
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
    "assistant.UsageInteraction",
]


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


def _actor(label, user):
    """Only UsageInteraction still names a user.

    Its `user` is the acting member, not the tenant — throttling is per person
    — so it stays NOT NULL and survives Task 13 (epic decision 1). The other
    four lose the column, so nothing here may name it.
    """
    return {"user": user} if label == "assistant.UsageInteraction" else {}


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
    row = baker.make(model, household=household, **_actor(label, user), **_required_extras(label))

    assert row.household == household


@pytest.mark.parametrize("label", AUTHORED)
def test_authored_model_records_who_wrote_it(label, user):
    from django.apps import apps

    model = apps.get_model(label)
    row = baker.make(model, household=baker.make(Household), created_by=user)

    assert row.created_by == user


@pytest.mark.parametrize("label", OWNED_ONLY)
def test_machine_written_model_has_no_created_by(label):
    """Not an oversight — asserted, so nobody 'fixes' it later. An embedding
    has no human author, and an interaction's `user` IS its author."""
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
    actor = _actor(label, user)
    baker.make(model, household=ours, **actor, **extras)
    baker.make(model, household=theirs, **actor, **extras)

    assert model.objects.for_household(ours).count() == 1


def test_two_members_cannot_create_the_same_memory_rule_twice():
    """The new capability's sharp edge: two people in one household share one
    set of memory rules, so the second person adding it must collide."""
    from django.db import IntegrityError

    household = baker.make(Household)
    baker.make(
        "assistant.MemoryRule",
        household=household,
        trigger="pague menos",
        field="category",
    )

    with pytest.raises(IntegrityError):
        baker.make(
            "assistant.MemoryRule",
            household=household,
            trigger="pague menos",
            field="category",
        )
