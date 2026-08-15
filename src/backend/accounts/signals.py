"""What happens the moment an account comes into existence.

`accounts.middleware.resolve_active_household` also mints a household for a
membership-less user, and deliberately keeps doing so — it is the fail-closed
answer for accounts created by `createsuperuser`, which never fires this
signal. The difference is the name: this path knows the email, so it can call
the household something its owner recognises.
"""

from allauth.account.models import EmailAddress
from allauth.account.signals import user_signed_up
from django.db import transaction
from django.dispatch import receiver

from accounts.models import Household, Membership, Role
from accounts.starter_data import seed_starter_data
from core.events import EventName, emit_once

_NAME_PREFIX = "Casa de "
_NAME_MAX_LENGTH = 120


def household_name_for(user) -> str:
    """``Casa de <email local part>``, clipped to fit ``Household.name``.

    Clipped rather than rejected: the name is a label, not an identifier, and
    a 200-character address must not be the thing that fails a signup.
    """
    email = getattr(user, "email", "") or ""
    label = email.split("@")[0] if "@" in email else (email or user.username)
    return f"{_NAME_PREFIX}{label}"[:_NAME_MAX_LENGTH]


@receiver(user_signed_up)
def create_household_for_new_user(request, user, **kwargs):
    """Give the new account its own household, as owner. Idempotent."""
    if Membership.objects.filter(user=user).exists():
        return
    with transaction.atomic():
        household = Household.objects.create(name=household_name_for(user))
        Membership.objects.create(user=user, household=household, role=Role.OWNER)
        # The funnel's T0. Time-to-activation is measured from this row rather
        # than from `date_joined` so that one query answers it and E14 does not
        # have to join the auth table to compute a product metric.
        emit_once(EventName.SIGNUP, household=household, user=user)

    # Outside the transaction above: the household and its owner membership
    # must be atomic with each other; the seeding must not be — see the
    # enqueue-race note in `accounts/starter_data.py`. Seeding is idempotent
    # and repairable by `manage.py seed_starter_data`, so a crash between the
    # two leaves a recoverable state rather than a corrupt one.
    seed_starter_data(household, user)


@receiver(user_signed_up)
def verify_invited_email(request, user, **kwargs):
    """An address that received an invitation link does not verify itself twice.

    Clicking a link emailed to an address is proof of control over it — the
    same proof allauth's own confirmation email establishes. Asking an invitee
    for that proof again is a round trip through an email client for no
    security gain, and it is exactly where an invite flow loses people.

    Hooked on ``user_signed_up`` rather than in an ``ACCOUNT_ADAPTER``, which
    is where this would naturally seem to belong. The adapter's hooks
    (``save_user``, ``should_send_confirmation_mail``) sit on either side of
    the moment that matters and neither is it: ``save_user`` runs before
    ``setup_user_email`` creates the ``EmailAddress`` row, so there is nothing
    to mark yet; ``should_send_confirmation_mail`` runs after ``perform_login``
    has already decided the account is unverified and bounced it to "confirme
    seu e-mail". This signal fires between the two — the row exists, and login
    has not been decided.

    The exemption is narrow on purpose: only the address the invitation was
    sent to, only while that invitation is still pending, and only for the
    session that actually opened the invitation link. Anything else is a
    stranger typing a stranger's address.
    """
    from accounts.invitations import invitation_for_token
    from accounts.views import PENDING_INVITE_SESSION_KEY

    session = getattr(request, "session", None)
    token = session.get(PENDING_INVITE_SESSION_KEY) if session else None
    if not token:
        return
    invitation = invitation_for_token(token)
    if invitation is None or not invitation.is_pending:
        return
    if invitation.email.lower() != (user.email or "").lower():
        return
    EmailAddress.objects.filter(user=user, email__iexact=user.email).update(verified=True)
