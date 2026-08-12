import pytest
from django.contrib.auth import get_user_model
from model_bakery import baker

from accounts.mixins import HouseholdScopedMixin
from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db


class _MembershipListView(HouseholdScopedMixin):
    """Minimal stand-in for a CBV: the mixin only needs get_queryset()."""

    model = Membership

    def __init__(self, request):
        self.request = request

    def get_queryset(self):
        return super().get_queryset()


def test_mixin_scopes_to_the_requests_household(rf):
    ours = baker.make(Household, name="Nossa")
    theirs = baker.make(Household, name="Deles")
    baker.make(Membership, household=ours, role=Role.OWNER)
    baker.make(Membership, household=theirs, role=Role.OWNER)

    request = rf.get("/")
    request.household = ours

    assert _MembershipListView(request).get_queryset().count() == 1


def test_mixin_without_a_household_yields_nothing(rf):
    baker.make(Membership, role=Role.OWNER)
    request = rf.get("/")
    request.household = None

    assert _MembershipListView(request).get_queryset().count() == 0


def test_mixin_raises_when_the_model_is_not_household_scoped(rf):
    """A model whose manager lacks for_request must fail loudly at the seam,
    not silently return an unscoped queryset."""

    class _UserView(HouseholdScopedMixin):
        model = get_user_model()

        def __init__(self, request):
            self.request = request

    request = rf.get("/")
    request.household = baker.make(Household)

    with pytest.raises(TypeError, match="not household-scoped"):
        _UserView(request).get_queryset()
