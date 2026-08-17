"""What a household spent is the household's record, not the leaver's.

E04 settled this for every other authored table: `created_by` is SET_NULL so
the ledger outlives the person who typed it. `UsageInteraction.user` was the
one column that still cascaded — which meant a member deleting their account
deleted the household's credit history along with themselves, quietly, and
took E07's cost report and E15's future invoice with it.
"""

import pytest
from django.db import models
from model_bakery import baker

from assistant.models import InteractionKind, UsageInteraction, UsageRecord

pytestmark = pytest.mark.django_db


def test_the_column_is_set_null_like_every_other_authored_column():
    field = UsageInteraction._meta.get_field("user")
    assert field.null is True
    assert field.remote_field.on_delete is models.SET_NULL


def test_deleting_a_member_leaves_the_households_interactions_behind(household, user):
    interaction = baker.make(
        UsageInteraction, household=household, user=user, kind=InteractionKind.TEXT
    )

    user.delete()

    interaction.refresh_from_db()
    assert interaction.user is None
    assert interaction.household_id == household.id


def test_deleting_a_member_leaves_the_cost_records_behind(household, user):
    """`UsageRecord.interaction` is SET_NULL, so before this change the records
    survived while their parent vanished — half a history, which is worse than
    either whole answer."""
    interaction = baker.make(
        UsageInteraction, household=household, user=user, kind=InteractionKind.TEXT
    )
    record = baker.make(UsageRecord, household=household, user=user, interaction=interaction)

    user.delete()

    record.refresh_from_db()
    assert record.user is None
    assert record.interaction_id == interaction.id


def test_deleting_the_household_still_takes_all_of_it(household, user):
    """SET_NULL on the person, CASCADE on the tenant. Loosening the first must
    not loosen the second."""
    baker.make(UsageInteraction, household=household, user=user, kind=InteractionKind.TEXT)
    household_id = household.id

    household.delete()

    assert not UsageInteraction.objects.filter(household_id=household_id).exists()
