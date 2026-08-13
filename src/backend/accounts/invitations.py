"""The invitation lifecycle. No HTTP, no templates, no request.

Kept pure so the four security properties S05-3 asks for — unguessable,
single-use, expiring, invalidated on use — are properties of *these
functions*, testable without a client. A property enforced in a view is a
property that one new view can quietly lose.

The raw token exists exactly once, as `create_invitation`'s second return
value, on its way into an email. Only its SHA-256 is stored, so a leaked
database backup contains nothing redeemable. SHA-256 without a salt or a work
factor is right here and would be wrong for a password: the input is 32 bytes
of `secrets` output, so there is no dictionary to attack and no low-entropy
guess to slow down.
"""

import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from accounts.models import Invitation, Membership, Role

#: 32 bytes -> 43 urlsafe characters. Well beyond guessing, still short enough
#: to survive an email client's line wrapping without being broken in half.
TOKEN_BYTES = 32
DEFAULT_TTL_DAYS = 7


class InvitationUnusable(Exception):
    """Base for every reason a token will not redeem."""


class InvitationNotFound(InvitationUnusable):
    pass


class InvitationExpired(InvitationUnusable):
    pass


class InvitationAlreadyUsed(InvitationUnusable):
    pass


class InvitationRevoked(InvitationUnusable):
    pass


def _hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_invitation(
    *, household, invited_by, email, role=Role.MEMBER, now=None, ttl_days=DEFAULT_TTL_DAYS
) -> tuple[Invitation, str]:
    """Mint an invitation and return it alongside its raw token.

    The raw token is returned rather than stored: this call is the only moment
    it exists in the process, and the caller's only job with it is to put it in
    a link and forget it.
    """
    now = now or timezone.now()
    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    invitation = Invitation.objects.create(
        household=household,
        created_by=invited_by,
        email=email,
        role=role,
        token_hash=_hash(raw_token),
        expires_at=now + timedelta(days=ttl_days),
    )
    return invitation, raw_token


def invitation_for_token(raw_token: str) -> Invitation | None:
    """The invitation a raw token refers to, valid or not, or ``None``.

    Deliberately unscoped: the redeemer is by definition not yet a member of
    the household, so a household-scoped read would return nothing. The token
    itself is the authorisation.
    """
    if not raw_token:
        return None
    return (
        Invitation.objects.select_related("household").filter(token_hash=_hash(raw_token)).first()
    )


def redeem_invitation(raw_token: str, user, *, now=None) -> Membership:
    """Turn a token into a membership. Raises ``InvitationUnusable``.

    Atomic, and the row is locked for the duration: two taps on the same link
    from a flaky mobile connection must produce one membership and one spent
    token, not two of either.
    """
    now = now or timezone.now()
    with transaction.atomic():
        invitation = (
            Invitation.objects.select_for_update()
            .select_related("household")
            .filter(token_hash=_hash(raw_token))
            .first()
        )
        if invitation is None:
            raise InvitationNotFound
        if invitation.revoked_at is not None:
            raise InvitationRevoked
        if invitation.accepted_at is not None:
            raise InvitationAlreadyUsed
        if invitation.is_expired(now=now):
            raise InvitationExpired

        membership, _ = Membership.objects.get_or_create(
            user=user,
            household=invitation.household,
            defaults={"role": invitation.role},
        )
        invitation.accepted_at = now
        invitation.save(update_fields=["accepted_at"])
        return membership


def revoke_invitation(invitation: Invitation, *, now=None) -> None:
    """Withdraw a pending invitation. Accepted ones are left alone.

    Revoking an already-accepted invitation is a no-op rather than an error:
    the membership it produced is what matters now, and removing that person is
    a different operation with different consequences.

    Re-reads the row under a lock rather than trusting the instance it was
    handed. The two operations that matter here happen seconds apart in the
    real world — an owner opens the members page, the invitee taps the link,
    the owner clicks "cancelar" — and the owner's `invitation` object was
    loaded before that tap. Deciding from it would stamp `revoked_at` on a row
    that has already produced a membership, leaving a record that contradicts
    itself.
    """
    now = now or timezone.now()
    with transaction.atomic():
        current = Invitation.objects.select_for_update().filter(pk=invitation.pk).first()
        if current is None or current.accepted_at is not None:
            return
        current.revoked_at = now
        current.save(update_fields=["revoked_at"])
    invitation.revoked_at = now
