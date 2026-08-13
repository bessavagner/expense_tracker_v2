"""Two roles, one place that decides what each may do.

E04 chose exactly two roles on purpose: an owner may invite and remove, a
member may only edit the ledger. Anything finer-grained is a separate epic.
The value of this module is that the rule is written once — the fourth
restatement of it inside a view is the one that gets it wrong.
"""

import pytest
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.views.generic import View
from model_bakery import baker

from accounts.models import Membership, Role
from accounts.permissions import OwnerRequiredMixin, is_owner


@pytest.mark.django_db
class TestIsOwner:
    def test_the_founder_of_a_household_is_its_owner(self, user, household):
        assert is_owner(user, household) is True

    def test_a_plain_member_is_not_an_owner(self, household):
        member = baker.make("core.CustomUser", email="membro@example.com")
        Membership.objects.create(user=member, household=household, role=Role.MEMBER)
        assert is_owner(member, household) is False

    def test_a_stranger_is_not_an_owner(self, household):
        stranger = baker.make("core.CustomUser", email="estranha@example.com")
        assert is_owner(stranger, household) is False

    def test_an_owner_of_another_household_is_not_an_owner_of_this_one(self, other_user, household):
        assert is_owner(other_user, household) is False

    def test_none_is_never_an_owner(self, household):
        assert is_owner(None, household) is False

    def test_nobody_owns_a_missing_household(self, user):
        assert is_owner(user, None) is False

    def test_an_anonymous_user_is_never_an_owner(self, household):
        """A permission check that raises on absent input becomes a 500 on the
        exact request that should have been a 403."""
        from django.contrib.auth.models import AnonymousUser

        assert is_owner(AnonymousUser(), household) is False


@pytest.mark.django_db
class TestOwnerRequiredMixin:
    class _View(OwnerRequiredMixin, View):
        def get(self, request, *args, **kwargs):
            from django.http import HttpResponse

            return HttpResponse("ok")

    def _request(self, user, household):
        request = RequestFactory().get("/")
        request.user = user
        request.household = household
        return request

    def test_an_owner_gets_through(self, user, household):
        response = self._View.as_view()(self._request(user, household))
        assert response.status_code == 200

    def test_a_member_is_refused(self, household):
        member = baker.make("core.CustomUser", email="membro@example.com")
        Membership.objects.create(user=member, household=household, role=Role.MEMBER)
        with pytest.raises(PermissionDenied):
            self._View.as_view()(self._request(member, household))

    def test_a_request_with_no_household_is_refused(self, user):
        with pytest.raises(PermissionDenied):
            self._View.as_view()(self._request(user, None))

    def test_a_request_the_middleware_never_touched_is_refused(self, user):
        """A bare RequestFactory has no `household` attribute at all. Reading it
        with getattr rather than dotting is what makes that a 403 instead of an
        AttributeError."""
        request = RequestFactory().get("/")
        request.user = user
        with pytest.raises(PermissionDenied):
            self._View.as_view()(request)
