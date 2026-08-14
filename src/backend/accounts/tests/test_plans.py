"""Plans, credit grants, and the tier a household prefers."""

import pytest

from accounts.models import Household, Plan
from core.tiers import Tier

pytestmark = pytest.mark.django_db


def test_exactly_one_plan_is_the_default():
    """`balance_for` needs a plan for a household that has none assigned."""
    assert Plan.objects.filter(is_default=True).count() == 1


def test_the_beta_plan_grants_credits():
    plan = Plan.objects.get(is_default=True)
    assert plan.monthly_credits > 0


def test_a_second_default_plan_is_rejected_by_the_database():
    from django.db.utils import IntegrityError

    with pytest.raises(IntegrityError):
        Plan.objects.create(name="Outro", slug="outro", monthly_credits=10, is_default=True)


def test_a_new_household_prefers_the_advanced_tier():
    hh = Household.objects.create(name="Casa")
    assert hh.preferred_tier == Tier.ADVANCED


def test_a_household_starts_with_no_explicit_plan():
    """Nullable so E15 can assign paid plans without backfilling everyone."""
    hh = Household.objects.create(name="Casa")
    assert hh.plan is None


def test_deleting_a_plan_does_not_delete_households():
    plan = Plan.objects.create(name="Temp", slug="temp", monthly_credits=5)
    hh = Household.objects.create(name="Casa", plan=plan)
    plan.delete()
    hh.refresh_from_db()
    assert hh.plan is None
