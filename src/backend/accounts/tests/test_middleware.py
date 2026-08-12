import pytest
from django.contrib.auth.models import AnonymousUser
from model_bakery import baker

from accounts.middleware import ACTIVE_HOUSEHOLD_SESSION_KEY, active_household_middleware
from accounts.models import Household, Membership, Role

pytestmark = pytest.mark.django_db


def _run_middleware(request):
    """Run the middleware over a request and hand back what it set."""
    active_household_middleware(lambda req: None)(request)
    return request.household


def test_anonymous_request_gets_no_household(rf):
    request = rf.get("/")
    request.user = AnonymousUser()
    request.session = {}

    assert _run_middleware(request) is None


def test_member_gets_their_only_household(rf, django_user_model):
    user = baker.make(django_user_model)
    household = baker.make(Household)
    baker.make(Membership, user=user, household=household, role=Role.OWNER)

    request = rf.get("/")
    request.user = user
    request.session = {}

    assert _run_middleware(request) == household


def test_session_choice_wins_when_the_user_is_a_member(rf, django_user_model):
    user = baker.make(django_user_model)
    first = baker.make(Household, name="Primeira")
    second = baker.make(Household, name="Segunda")
    baker.make(Membership, user=user, household=first, role=Role.OWNER)
    baker.make(Membership, user=user, household=second, role=Role.MEMBER)

    request = rf.get("/")
    request.user = user
    request.session = {ACTIVE_HOUSEHOLD_SESSION_KEY: str(second.id)}

    assert _run_middleware(request) == second


def test_session_pointing_at_a_foreign_household_is_ignored(rf, django_user_model):
    """The attack: paste someone else's household id into your session."""
    user = baker.make(django_user_model)
    mine = baker.make(Household, name="Minha")
    theirs = baker.make(Household, name="Alheia")
    baker.make(Membership, user=user, household=mine, role=Role.OWNER)
    baker.make(Membership, household=theirs, role=Role.OWNER)

    request = rf.get("/")
    request.user = user
    request.session = {ACTIVE_HOUSEHOLD_SESSION_KEY: str(theirs.id)}

    assert _run_middleware(request) == mine


def test_session_holding_a_malformed_id_falls_back(rf, django_user_model):
    """A tampered cookie is not a 500. ``household_id`` is a UUID column, so a
    non-UUID string would raise on the way into the query."""
    user = baker.make(django_user_model)
    mine = baker.make(Household, name="Minha")
    baker.make(Membership, user=user, household=mine, role=Role.OWNER)

    request = rf.get("/")
    request.user = user
    request.session = {ACTIVE_HOUSEHOLD_SESSION_KEY: "not-a-uuid"}

    assert _run_middleware(request) == mine


def test_resolution_is_written_back_to_the_session(rf, django_user_model):
    user = baker.make(django_user_model)
    household = baker.make(Household)
    baker.make(Membership, user=user, household=household, role=Role.OWNER)

    request = rf.get("/")
    request.user = user
    request.session = {}

    _run_middleware(request)

    assert request.session[ACTIVE_HOUSEHOLD_SESSION_KEY] == str(household.id)


def test_user_with_no_membership_gets_none(rf, django_user_model):
    """A user created before the seed migration, or by createsuperuser after
    it. Fails closed rather than borrowing somebody's ledger."""
    request = rf.get("/")
    request.user = baker.make(django_user_model)
    request.session = {}

    assert _run_middleware(request) is None
