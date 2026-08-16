"""The two funnel steps E11 left unmeasured.

Drop-off is only derivable if every step between signup and activation emits.
Email verification is where a real funnel loses people; the photograph is what
separates "never tried the wedge" from "tried it and extraction failed".
"""

import pytest
from model_bakery import baker

from accounts.models import Household, Membership, Role
from core.events import ONCE_PER_HOUSEHOLD, EventName

pytestmark = pytest.mark.django_db


def test_email_verified_happens_at_most_once_per_household():
    assert EventName.EMAIL_VERIFIED in ONCE_PER_HOUSEHOLD


def test_receipt_photo_is_countable():
    """Photos taken against receipts committed IS the extraction failure rate.
    A once-per-household event could not express it."""
    assert EventName.RECEIPT_PHOTO not in ONCE_PER_HOUSEHOLD


def test_confirming_an_email_emits_once(django_user_model):
    """Driven through the allauth signal rather than by calling emit directly —
    the wiring is the thing that can break."""
    from allauth.account.models import EmailAddress
    from allauth.account.signals import email_confirmed

    from core.models import ProductEvent

    user = baker.make(django_user_model, username="stranger", email="s@example.com")
    household = baker.make(Household, name="Casa de stranger")
    baker.make(Membership, household=household, user=user, role=Role.OWNER)
    address = baker.make(EmailAddress, user=user, email=user.email, verified=True)

    email_confirmed.send(sender=EmailAddress, request=None, email_address=address)
    email_confirmed.send(sender=EmailAddress, request=None, email_address=address)

    assert (
        ProductEvent.objects.filter(household=household, name=EventName.EMAIL_VERIFIED).count() == 1
    )
