"""S04-6: no domain model can be read across a household boundary.

Parameterized over ``household_owned_models()`` — *discovered* from the base
class, never a hand-written list. A model added later that inherits the base
is covered here automatically; one that forgets to inherit it fails
``test_every_domain_model_is_household_owned``. That pair is the whole point:
the epic's failure mode is a model nobody remembered to scope.

``PaymentMethodClosingDay`` has no household column by decision 4 of the epic.
It is covered through its parent instead, at the bottom of this file.
"""

import pytest
from model_bakery import baker

from accounts.models import Household, household_owned_models

pytestmark = pytest.mark.django_db

# Models in the domain apps that deliberately carry no household column.
# Adding to this set is a decision, not a convenience — every entry needs a
# reason recorded in the epic.
EXEMPT = {
    # Epic decision 4: scoped transitively through PaymentMethod.
    "finances.PaymentMethodClosingDay",
    # E07: global product configuration, not tenant data. What OpenAI charges
    # for a model is the same fact for every household, and giving it a
    # household column would mean one price row per tenant to keep in sync —
    # the opposite of the "correct a price without a deploy" property spec D4
    # asked for. No user-supplied data reaches this table; only the admin
    # writes it.
    "assistant.ModelPrice",
    # E07, same reasoning as ModelPrice: the (tier x kind) credit grid is one
    # global product decision, not a per-tenant one. Per-household pricing is
    # E15's problem and would be a new column, not a household FK on all six
    # rows. `accounts.Plan` is the same kind of thing; it escapes this list
    # only because the scan covers `finances` and `assistant`.
    "assistant.CreditPrice",
}


def _extras(model):
    """Fields model_bakery cannot invent.

    pgvector's ``VectorField`` has no baker generator, so the embedding has to
    be handed over explicitly.
    """
    if model._meta.label == "assistant.MemoryEmbedding":
        return {"embedding": [0.1] * 1536}
    return {}


def _labels():
    return sorted(m._meta.label for m in household_owned_models())


@pytest.mark.parametrize("label", _labels())
def test_model_rejects_rows_from_another_household(label):
    from django.apps import apps

    model = apps.get_model(label)
    ours = baker.make(Household, name="Nossa")
    theirs = baker.make(Household, name="Deles")
    extras = _extras(model)
    mine = baker.make(model, household=ours, **extras)
    baker.make(model, household=theirs, **extras)

    scoped = model.objects.for_household(ours)

    assert list(scoped) == [mine]


@pytest.mark.parametrize("label", _labels())
def test_model_with_no_household_returns_nothing_not_everything(label):
    """Fail closed. An unresolved tenant must never mean 'the whole table'."""
    from django.apps import apps

    model = apps.get_model(label)
    baker.make(model, household=baker.make(Household), **_extras(model))

    assert model.objects.for_household(None).count() == 0


def test_every_domain_model_is_household_owned():
    """The counterpart that catches a model added *without* the base class."""
    from django.apps import apps

    owned = {m._meta.label for m in household_owned_models()}
    domain = {
        m._meta.label
        for app in ("finances", "assistant")
        for m in apps.get_app_config(app).get_models()
    }

    unscoped = sorted(domain - owned - EXEMPT)

    assert not unscoped, (
        "These domain models carry no household column. Inherit "
        f"HouseholdOwnedModel, or add them to EXEMPT with a reason: {unscoped}"
    )


def test_closing_day_is_unreachable_from_a_foreign_payment_method(
    user, household, other_user, other_household
):
    """Decision 4, asserted rather than assumed: the only route to a closing
    day is through a PaymentMethod, so scoping the parent scopes the child."""
    from finances.models import PaymentMethod, PaymentMethodClosingDay

    theirs = baker.make(
        PaymentMethod,
        household=other_household,
        name="Cartao do vizinho",
        type="credit_card",
    )
    baker.make(
        PaymentMethodClosingDay,
        payment_method=theirs,
        month="2026-03-01",
        closing_day=12,
    )

    reachable = PaymentMethodClosingDay.objects.filter(
        payment_method__in=PaymentMethod.objects.for_household(household)
    )

    assert reachable.count() == 0
