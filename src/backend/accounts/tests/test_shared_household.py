"""The point of the whole epic: two people, one ledger.

Every other test in this branch asserts a boundary holds. This one asserts the
boundary is in the right place — Amanda, a member of Vagner's household, sees
Vagner's entries. Through the real HTTP path, because the middleware resolving
`request.household` is the part that has to work.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from accounts.models import Membership, Role
from finances.models.entry import EntryType

pytestmark = pytest.mark.django_db


@pytest.fixture
def amanda(user, household):
    """A second person in the *same* household."""
    person = baker.make("core.CustomUser", username="amanda")
    baker.make(Membership, user=person, household=household, role=Role.MEMBER)
    return person


@pytest.fixture
def amandas_client(amanda):
    client = Client()
    client.force_login(amanda)
    return client


@pytest.fixture
def vagners_entry(user, household):
    category = baker.make("finances.Category", household=household, name="Mercado")
    pm = baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    return baker.make(
        "finances.Entry",
        household=household,
        created_by=user,
        category=category,
        payment_method=pm,
        amount=Decimal("42.00"),
        description="Feira da semana",
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )


def test_a_member_sees_the_other_members_entries(amandas_client, vagners_entry):
    response = amandas_client.get(reverse("finances:entries_month", args=[2026, 3]))

    assert response.status_code == 200
    assert "Feira da semana" in response.content.decode()


def test_a_member_can_open_the_other_members_entry(amandas_client, vagners_entry):
    """Not merely visible in a list — editable. Shared ledger, not shared view."""
    response = amandas_client.get(reverse("finances:entry_edit_modal", args=[vagners_entry.pk]))

    assert response.status_code == 200


def test_provenance_survives_the_sharing(vagners_entry, user):
    """Shared does not mean anonymous — E17 surfaces who wrote a row."""
    assert vagners_entry.created_by == user


def test_a_stranger_still_gets_a_404(logged_client, other_user, other_household):
    """The control: membership is what grants access, not being logged in."""
    theirs = baker.make(
        "finances.Entry",
        household=other_household,
        date=date(2026, 3, 10),
        billing_month=date(2026, 3, 1),
        entry_type=EntryType.REGULAR,
    )

    response = logged_client.get(reverse("finances:entry_edit_modal", args=[theirs.pk]))

    assert response.status_code == 404
