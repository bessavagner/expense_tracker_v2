"""A brand-new account owns a household from its first request.

The middleware would eventually mint one anyway, but it names the household
after the username — and from E05 the username is a generated slug nobody
chose. Doing it at signup is what makes the name readable, and what makes the
role `owner` rather than incidental.
"""

import pytest
from allauth.account.signals import user_signed_up
from model_bakery import baker

from accounts.models import Membership, Role
from accounts.signals import household_name_for


@pytest.mark.django_db
class TestSignupCreatesHousehold:
    def test_signing_up_creates_one_household_owned_by_the_signer(self):
        user = baker.make("core.CustomUser", username="a1b2c3", email="rita@example.com")
        user_signed_up.send(sender=type(user), request=None, user=user)

        memberships = Membership.objects.filter(user=user)
        assert memberships.count() == 1
        assert memberships.first().role == Role.OWNER

    def test_the_household_is_named_after_the_email_not_the_slug_username(self):
        user = baker.make("core.CustomUser", username="a1b2c3", email="rita@example.com")
        user_signed_up.send(sender=type(user), request=None, user=user)

        household = Membership.objects.get(user=user).household
        assert household.name == "Casa de rita"
        assert "a1b2c3" not in household.name

    def test_it_is_idempotent(self):
        """A resent signal must not hand one person two households."""
        user = baker.make("core.CustomUser", username="a1b2c3", email="rita@example.com")
        user_signed_up.send(sender=type(user), request=None, user=user)
        user_signed_up.send(sender=type(user), request=None, user=user)

        assert Membership.objects.filter(user=user).count() == 1


class TestHouseholdName:
    def test_it_clips_to_the_column_width(self):
        """Household.name is varchar(120); a long local part must not overflow."""
        user = type("U", (), {"email": "x" * 200 + "@example.com", "username": "u"})()
        assert len(household_name_for(user)) <= 120

    def test_it_falls_back_to_the_username_when_there_is_no_email(self):
        user = type("U", (), {"email": "", "username": "operador"})()
        assert household_name_for(user) == "Casa de operador"
