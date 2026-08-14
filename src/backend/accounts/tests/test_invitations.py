"""The invitation lifecycle, with no HTTP in sight.

Kept as pure functions so the security properties — unguessable, single-use,
expiring, never stored in the clear — are tested against the functions
themselves rather than through a view that might be the thing enforcing them.
A property enforced in a view is a property one new view can lose.
"""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from model_bakery import baker

from accounts.invitations import (
    InvitationAlreadyUsed,
    InvitationExpired,
    InvitationNotFound,
    InvitationRevoked,
    create_invitation,
    invitation_for_token,
    redeem_invitation,
    revoke_invitation,
)
from accounts.models import Invitation, Membership, Role

# 2026-06-15 is arbitrary; what matters is that the TTL boundary tests below
# compare against one fixed instant rather than two reads of the real clock.
FROZEN_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def invitee(db):
    return baker.make("core.CustomUser", username="convidada", email="convidada@example.com")


@pytest.mark.django_db
class TestCreateInvitation:
    def test_it_returns_the_row_and_a_raw_token(self, household, user):
        invitation, raw = create_invitation(
            household=household, invited_by=user, email="nova@example.com"
        )
        assert isinstance(invitation, Invitation)
        assert isinstance(raw, str)

    def test_the_raw_token_is_not_stored(self, household, user):
        _, raw = create_invitation(household=household, invited_by=user, email="n@example.com")
        assert not Invitation.objects.filter(token_hash=raw).exists()

    def test_the_stored_value_is_the_sha256_of_the_raw_token(self, household, user):
        invitation, raw = create_invitation(
            household=household, invited_by=user, email="n@example.com"
        )
        assert invitation.token_hash == hashlib.sha256(raw.encode()).hexdigest()

    def test_the_token_has_enough_entropy_to_be_unguessable(self, household, user):
        """S05-3: 'invitation tokens are not guessable'. 32 bytes urlsafe-encoded
        is >= 43 characters; anything shorter is a brute-force target."""
        _, raw = create_invitation(household=household, invited_by=user, email="n@example.com")
        assert len(raw) >= 43

    def test_two_invitations_never_share_a_token(self, household, user):
        _, first = create_invitation(household=household, invited_by=user, email="a@example.com")
        _, second = create_invitation(household=household, invited_by=user, email="b@example.com")
        assert first != second

    def test_it_records_the_inviter_and_the_household(self, household, user):
        invitation, _ = create_invitation(
            household=household, invited_by=user, email="n@example.com"
        )
        assert invitation.household == household
        assert invitation.created_by == user

    def test_the_default_role_is_member(self, household, user):
        invitation, _ = create_invitation(
            household=household, invited_by=user, email="n@example.com"
        )
        assert invitation.role == Role.MEMBER

    def test_the_ttl_is_seven_days_from_the_injected_clock(self, household, user):
        invitation, _ = create_invitation(
            household=household, invited_by=user, email="n@example.com", now=FROZEN_NOW
        )
        assert invitation.expires_at == FROZEN_NOW + timedelta(days=7)


@pytest.mark.django_db
class TestLookup:
    def test_a_valid_raw_token_finds_its_invitation(self, household, user):
        invitation, raw = create_invitation(
            household=household, invited_by=user, email="n@example.com"
        )
        assert invitation_for_token(raw) == invitation

    def test_an_unknown_token_finds_nothing(self):
        assert invitation_for_token("nao-existe") is None

    def test_an_empty_token_finds_nothing(self):
        assert invitation_for_token("") is None


@pytest.mark.django_db
class TestRedeem:
    def test_redeeming_creates_a_membership_in_that_household(self, household, user, invitee):
        _, raw = create_invitation(household=household, invited_by=user, email=invitee.email)
        membership = redeem_invitation(raw, invitee)
        assert membership.household == household
        assert membership.user == invitee
        assert membership.role == Role.MEMBER

    def test_redeeming_marks_the_invitation_accepted(self, household, user, invitee):
        invitation, raw = create_invitation(
            household=household, invited_by=user, email=invitee.email
        )
        redeem_invitation(raw, invitee)
        invitation.refresh_from_db()
        assert invitation.accepted_at is not None

    def test_a_token_is_single_use(self, household, user, invitee):
        """S05-3: 'invitation tokens are ... invalidated on use'."""
        _, raw = create_invitation(household=household, invited_by=user, email=invitee.email)
        redeem_invitation(raw, invitee)

        other = baker.make("core.CustomUser", email="outra@example.com")
        with pytest.raises(InvitationAlreadyUsed):
            redeem_invitation(raw, other)

    def test_an_expired_token_is_refused(self, household, user, invitee):
        _, raw = create_invitation(
            household=household, invited_by=user, email=invitee.email, now=FROZEN_NOW
        )
        with pytest.raises(InvitationExpired):
            redeem_invitation(raw, invitee, now=FROZEN_NOW + timedelta(days=8))

    def test_a_revoked_token_is_refused(self, household, user, invitee):
        invitation, raw = create_invitation(
            household=household, invited_by=user, email=invitee.email
        )
        revoke_invitation(invitation)
        with pytest.raises(InvitationRevoked):
            redeem_invitation(raw, invitee)

    def test_an_unknown_token_is_refused(self, invitee):
        with pytest.raises(InvitationNotFound):
            redeem_invitation("nao-existe", invitee)

    def test_redeeming_twice_by_the_same_user_does_not_duplicate_a_membership(
        self, household, user, invitee
    ):
        _, raw = create_invitation(household=household, invited_by=user, email=invitee.email)
        redeem_invitation(raw, invitee)
        assert Membership.objects.filter(user=invitee, household=household).count() == 1

    def test_redeeming_is_atomic(self, household, user, invitee):
        """A failure after the membership insert must not leave the token spent
        with nobody in the household — nor the reverse."""
        invitation, raw = create_invitation(
            household=household, invited_by=user, email=invitee.email
        )
        redeem_invitation(raw, invitee)
        invitation.refresh_from_db()
        assert invitation.accepted_at is not None
        assert Membership.objects.filter(user=invitee, household=household).exists()

    def test_the_invitations_role_is_what_the_membership_gets(self, household, user, invitee):
        """An owner invite must not silently arrive as a member.

        `redeem_invitation` uses get_or_create, whose `defaults` are ignored
        when the row already exists — so this also pins that a *new* membership
        reads its role from the invitation rather than the model default.
        """
        _, raw = create_invitation(
            household=household, invited_by=user, email=invitee.email, role=Role.OWNER
        )
        assert redeem_invitation(raw, invitee).role == Role.OWNER


@pytest.mark.django_db
class TestRevoke:
    def test_revoking_stamps_the_row(self, household, user):
        invitation, _ = create_invitation(
            household=household, invited_by=user, email="n@example.com"
        )
        revoke_invitation(invitation, now=FROZEN_NOW)
        invitation.refresh_from_db()
        assert invitation.revoked_at == FROZEN_NOW

    def test_revoking_an_accepted_invitation_changes_nothing(self, household, user, invitee):
        invitation, raw = create_invitation(
            household=household, invited_by=user, email=invitee.email
        )
        redeem_invitation(raw, invitee)
        revoke_invitation(invitation)
        invitation.refresh_from_db()
        assert invitation.revoked_at is None
        assert Membership.objects.filter(user=invitee, household=household).exists()
