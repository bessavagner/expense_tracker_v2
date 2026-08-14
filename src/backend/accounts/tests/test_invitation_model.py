"""What an invitation is, before anything sends or redeems one.

Inherits AuthoredHouseholdModel deliberately: that is what makes `household`
NOT NULL, gives `created_by` SET_NULL semantics (an owner who deletes their
account must not delete the household's invitation history), and puts the row
inside E04's isolation ratchet without anyone maintaining a list.
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from model_bakery import baker

from accounts.models import AuthoredHouseholdModel, Invitation, Role, household_owned_models

# Frozen so `is_expired` is compared against a fixed instant rather than the
# real clock: the assertions below are about an hour either side of an expiry,
# and a suite that reads `now()` twice can straddle it.
FROZEN_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.mark.django_db
class TestInvitationIsHouseholdOwned:
    def test_it_inherits_the_tenancy_base(self):
        assert issubclass(Invitation, AuthoredHouseholdModel)

    def test_the_ratchet_discovers_it(self):
        """E04's isolation test enumerates by base class, not by a list."""
        assert Invitation in household_owned_models()

    def test_household_is_not_nullable(self):
        assert Invitation._meta.get_field("household").null is False


@pytest.mark.django_db
class TestTokenHashIsUnique:
    def test_two_invitations_cannot_share_a_token_hash(self, household):
        baker.make(Invitation, household=household, token_hash="a" * 64)
        with pytest.raises(IntegrityError), transaction.atomic():
            baker.make(Invitation, household=household, token_hash="a" * 64)


@pytest.mark.django_db
class TestPendingAndExpired:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self, time_machine):
        time_machine.move_to(FROZEN_NOW, tick=False)

    def _invite(self, household, **kwargs):
        defaults = {
            "household": household,
            "email": "convidada@example.com",
            "role": Role.MEMBER,
            "token_hash": "b" * 64,
            "expires_at": timezone.now() + timedelta(days=7),
        }
        defaults.update(kwargs)
        return Invitation.objects.create(**defaults)

    def test_a_fresh_invitation_is_pending(self, household):
        assert self._invite(household).is_pending is True

    def test_an_accepted_invitation_is_not_pending(self, household):
        invite = self._invite(household, accepted_at=timezone.now())
        assert invite.is_pending is False

    def test_a_revoked_invitation_is_not_pending(self, household):
        invite = self._invite(household, revoked_at=timezone.now())
        assert invite.is_pending is False

    def test_an_expired_invitation_is_not_pending(self, household):
        invite = self._invite(household, expires_at=timezone.now() - timedelta(seconds=1))
        assert invite.is_expired() is True
        assert invite.is_pending is False

    def test_expiry_accepts_an_injected_clock(self, household):
        invite = self._invite(household, expires_at=FROZEN_NOW + timedelta(days=7))
        assert invite.is_expired(now=FROZEN_NOW + timedelta(days=6)) is False
        assert invite.is_expired(now=FROZEN_NOW + timedelta(days=8)) is True
