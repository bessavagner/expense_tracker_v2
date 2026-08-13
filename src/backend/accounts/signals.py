"""What happens the moment an account comes into existence.

`accounts.middleware.resolve_active_household` also mints a household for a
membership-less user, and deliberately keeps doing so — it is the fail-closed
answer for accounts created by `createsuperuser`, which never fires this
signal. The difference is the name: this path knows the email, so it can call
the household something its owner recognises.
"""

from allauth.account.signals import user_signed_up
from django.db import transaction
from django.dispatch import receiver

from accounts.models import Household, Membership, Role

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
