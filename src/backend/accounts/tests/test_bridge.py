"""The phase 2-3 write bridge, and — just as important — its limits.

DELETE THIS FILE IN PHASE 4, together with accounts/bridge.py.
"""

import pytest
from model_bakery import baker

from accounts.bridge import household_for_writer
from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return baker.make("core.CustomUser", username="vagner")


def test_a_saved_row_gets_its_writers_household(user):
    household = baker.make(Household)
    baker.make(Membership, user=user, household=household, role=Role.OWNER)

    entry = baker.make("finances.Entry", user=user)

    assert entry.household == household
    assert entry.created_by == user


def test_an_explicit_household_is_never_overwritten(user):
    """The bridge fills a gap; it does not have an opinion. A write site that
    has been converted in phase 3 must win."""
    mine = baker.make(Household, name="Minha")
    theirs = baker.make(Household, name="Alheia")
    baker.make(Membership, user=user, household=mine, role=Role.OWNER)

    entry = baker.make("finances.Entry", user=user, household=theirs)

    assert entry.household == theirs


def test_a_user_with_no_membership_gets_one(user):
    """Tests build users with baker and never create a Membership. Rather than
    leave those rows tenant-less, give the user their own household by the same
    rule the seed migration used — so test data is coherent, and a production
    user who somehow has no membership writes into their own ledger rather
    than somebody else's."""
    entry = baker.make("finances.Entry", user=user)

    assert entry.household is not None
    assert Membership.objects.filter(user=user, role=Role.OWNER).count() == 1


def test_two_users_do_not_share_a_bridged_household(user):
    other = baker.make("core.CustomUser", username="amanda")

    mine = baker.make("finances.Entry", user=user)
    theirs = baker.make("finances.Entry", user=other)

    assert mine.household != theirs.household


def test_household_for_writer_of_none_is_none():
    assert household_for_writer(None) is None


def test_bulk_create_is_not_bridged(user):
    """Stated, not hidden: pre_save does not fire for bulk_create. Every bulk
    write site must set household itself — Task 5 Step 5 fixes the only one in
    production code, and this test is the reason a future one gets caught."""
    from finances.models import Entry

    category = baker.make("finances.Category", user=user)
    method = baker.make("finances.PaymentMethod", user=user, type="pix")
    Entry.objects.bulk_create(
        [
            Entry(
                user=user,
                date="2026-03-01",
                amount="10.00",
                description="bulk",
                category=category,
                payment_method=method,
                billing_month="2026-03-01",
                billing_month_override=True,
            )
        ]
    )

    assert Entry.objects.filter(description="bulk", household__isnull=True).count() == 1
