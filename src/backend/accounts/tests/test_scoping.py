import pytest
from django.contrib.auth import get_user_model
from model_bakery import baker

from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_households():
    ours = baker.make(Household, name="Nossa")
    theirs = baker.make(Household, name="Deles")
    baker.make(Membership, household=ours, role=Role.OWNER)
    baker.make(Membership, household=theirs, role=Role.OWNER)
    return ours, theirs


def test_for_household_returns_only_that_households_rows(two_households):
    ours, _theirs = two_households
    assert list(Membership.objects.for_household(ours)) == list(ours.memberships.all())


def test_for_household_of_none_returns_nothing_not_everything(two_households):
    """The failure mode that matters: an unresolved household must never
    degrade into an unscoped queryset."""
    assert Membership.objects.for_household(None).count() == 0


def test_for_request_uses_the_requests_household(rf, two_households):
    ours, theirs = two_households
    request = rf.get("/")
    request.household = ours

    scoped = Membership.objects.for_request(request)

    assert scoped.count() == 1
    assert scoped.first().household == ours


def test_for_request_without_a_household_attribute_returns_nothing(rf, two_households):
    request = rf.get("/")  # no .household — e.g. middleware not installed

    assert Membership.objects.for_request(request).count() == 0


def test_scoping_survives_further_filtering(two_households):
    ours, _theirs = two_households
    user = baker.make(get_user_model())
    baker.make(Membership, household=ours, user=user, role=Role.MEMBER)

    scoped = Membership.objects.for_household(ours).filter(role=Role.MEMBER)

    assert scoped.count() == 1
    assert scoped.first().user == user
