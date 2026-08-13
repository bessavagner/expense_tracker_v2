"""The two `PaymentMethod.objects.filter(pk=...)` unions are NOT leaks.

`views/cockpit.py` unions an unscoped single-pk lookup onto an already-scoped
queryset, so the entry's current payment method stays selectable in the form
even if it was later deactivated. The pk comes from an object that was itself
household-scoped, so the union cannot reach another household — but nothing
asserted that until now. The epic asked for this test by name.

The plan named a `cockpit_entry_edit_modal` route; the real union sites are the
parcelamento edit modal and the manage modal, both keyed on an installment
Entry. Both go through `_patch_entry_querysets`, so one covers the shape.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from model_bakery import baker

from finances.models.entry import EntryType

pytestmark = pytest.mark.django_db


@pytest.fixture
def foreign_payment_method(other_user, other_household):
    return baker.make(
        "finances.PaymentMethod",
        household=other_household,
        name="Cartão do vizinho",
        type="credit",
    )


@pytest.fixture
def entry_on_a_deactivated_method(user, household):
    """An installment entry whose payment method is no longer active.

    Deactivated on purpose: the scoped half of the union filters on
    `is_active=True`, so this method reaches the form *only* through the
    unscoped pk lookup — which is exactly the branch under test.
    """
    mine = baker.make(
        "finances.PaymentMethod",
        household=household,
        name="Meu Pix",
        type="pix",
        is_active=False,
    )
    category = baker.make("finances.Category", household=household, name="Minha")
    return baker.make(
        "finances.Entry",
        household=household,
        category=category,
        payment_method=mine,
        amount=Decimal("10.00"),
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.INSTALLMENT,
    )


def test_edit_modal_union_cannot_surface_a_foreign_payment_method(
    logged_client, entry_on_a_deactivated_method, foreign_payment_method
):
    entry = entry_on_a_deactivated_method

    response = logged_client.get(
        reverse("finances:cockpit_parcelamento_edit_modal", args=[2026, 3, entry.pk])
    )
    body = response.content.decode()

    assert response.status_code == 200
    # The union's whole purpose: the entry's own (deactivated) method is offered.
    assert "Meu Pix" in body
    # And the neighbour's is not.
    assert "Cartão do vizinho" not in body
