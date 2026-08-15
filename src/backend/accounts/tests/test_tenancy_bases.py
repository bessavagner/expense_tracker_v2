"""The abstract bases every re-tenanted domain model inherits.

Re-tenanting a model is a change to its base class, not a copy-pasted field —
so there is one definition of what "belongs to a household" means, and phase 4
can enumerate the models rather than maintain a list by hand.
"""

import pytest
from django.db import models
from model_bakery import baker

from accounts.models import (
    AuthoredHouseholdModel,
    Household,
    HouseholdOwnedModel,
    household_owned_models,
)
from accounts.scoping import HouseholdScopedQuerySet

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


def test_bases_are_abstract():
    """Abstract, or Django would build two pointless tables."""
    assert HouseholdOwnedModel._meta.abstract
    assert AuthoredHouseholdModel._meta.abstract


def test_registry_finds_entry():
    from finances.models import Entry

    assert Entry in household_owned_models()


def test_registry_excludes_the_abstract_bases():
    for model in household_owned_models():
        assert not model._meta.abstract


def test_registry_excludes_payment_method_closing_day():
    """Decision 4: it is scoped transitively through PaymentMethod and must
    NOT grow a household column. If it appears here, someone re-tenanted it."""
    from finances.models import PaymentMethodClosingDay

    assert PaymentMethodClosingDay not in household_owned_models()


def test_every_registered_model_has_a_scoped_manager():
    for model in household_owned_models():
        assert isinstance(model.objects.all(), HouseholdScopedQuerySet), (
            f"{model.__name__} inherits the base but lost the scoped manager"
        )


def test_household_fk_cascades_and_is_required():
    field = HouseholdOwnedModel._meta.get_field("household")
    assert field.null is False  # phase 4: the database enforces tenancy
    assert field.remote_field.on_delete is models.CASCADE


def test_created_by_survives_the_author_leaving_the_household():
    """SET_NULL, not CASCADE: deleting a person must never delete the family's
    financial history. This is the whole point of splitting user into
    household + created_by."""
    field = AuthoredHouseholdModel._meta.get_field("created_by")
    assert field.null is True
    assert field.remote_field.on_delete is models.SET_NULL


def test_registry_holds_exactly_the_sixteen_household_owned_models():
    """A model that grows a household column without a decision, or loses one,
    changes this number. That is the point — it should be a conversation, not
    a silent diff.

    Thirteen of these are E04's re-tenanted models. The fourteenth,
    `accounts.Invitation`, is E05's and was born household-owned: it inherits
    the base precisely so the cross-household isolation suite covers it without
    anyone adding it to a list. This assertion is that conversation happening.

    The fifteenth is E07's `assistant.UsageRecord`. It is household-owned
    because the operator report totals spend per household and a member must
    never see a neighbour's costs — the same reason `UsageInteraction` is.
    E07's other three new tables are NOT here and should not be:
    `ModelPrice`, `CreditPrice` and `Plan` are global product configuration,
    identical for every tenant.

    The sixteenth is E11's `core.ProductEvent`. It carries a household so an
    event is scoped and isolated exactly like every other row here — a member
    must never see a neighbour's onboarding progress or activation moment.
    """
    expected = {
        "accounts.Invitation",
        "finances.Entry",
        "finances.Income",
        "finances.Category",
        "finances.PaymentMethod",
        "finances.Budget",
        "finances.InstallmentPlan",
        "finances.SystemicExpense",
        "finances.ImportBatch",
        "assistant.ChatMessage",
        "assistant.MemoryRule",
        "assistant.ReceiptDraft",
        "assistant.MemoryEmbedding",
        "assistant.UsageInteraction",
        "assistant.UsageRecord",
        "core.ProductEvent",
    }
    actual = {m._meta.label for m in household_owned_models()}

    assert actual == expected


def test_household_deletion_takes_its_rows_with_it(user):
    from finances.models import Entry

    household = baker.make(Household)
    baker.make(Entry, household=household)

    household.delete()

    assert Entry.objects.count() == 0
