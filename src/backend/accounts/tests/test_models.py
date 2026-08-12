import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from model_bakery import baker

from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db


def test_household_has_uuid_pk_and_str():
    household = baker.make(Household, name="Casa Bessa")
    assert str(household) == "Casa Bessa"
    # UUID pk, matching the convention in finances/models/category.py
    assert len(str(household.id)) == 36


def test_user_can_belong_to_two_households():
    """Decision 1: multi-household in the schema, one active in the UI."""
    user = baker.make(get_user_model())
    first = baker.make(Household, name="Casa A")
    second = baker.make(Household, name="Casa B")

    baker.make(Membership, user=user, household=first, role=Role.OWNER)
    baker.make(Membership, user=user, household=second, role=Role.MEMBER)

    assert user.memberships.count() == 2


def test_same_user_cannot_join_one_household_twice():
    user = baker.make(get_user_model())
    household = baker.make(Household)
    baker.make(Membership, user=user, household=household, role=Role.OWNER)

    with pytest.raises(IntegrityError):
        Membership.objects.create(user=user, household=household, role=Role.MEMBER)


def test_roles_are_exactly_owner_and_member():
    """Decision 2: resist any third role. A viewer role is a new epic."""
    assert [choice[0] for choice in Role.choices] == ["owner", "member"]


def test_memberships_order_oldest_first_for_owner_promotion():
    """Decision 3: the last owner's departure promotes the longest-standing
    member, so creation order must be both recorded and the default ordering."""
    household = baker.make(Household)
    older = baker.make(Membership, household=household, role=Role.MEMBER)
    newer = baker.make(Membership, household=household, role=Role.MEMBER)

    assert list(household.memberships.all()) == [older, newer]
    assert older.created_at <= newer.created_at
