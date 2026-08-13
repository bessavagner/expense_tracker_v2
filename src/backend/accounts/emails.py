"""Outbound mail for invitations.

Separate from `accounts.invitations` on purpose: that module is pure, and
keeping it that way is what lets the security properties be tested without a
mail backend. This module is the only place that knows a raw token becomes a
URL.
"""

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse


def send_invitation(invitation, raw_token: str, request=None) -> None:
    """Email the invitee their link.

    Takes the raw token as an argument rather than reading it off the row,
    because the row does not have it — only its hash is stored. This is the
    last point in the process where the raw token exists.
    """
    path = reverse("invite_accept", args=[raw_token])
    url = request.build_absolute_uri(path) if request is not None else path
    context = {
        "url": url,
        "household": invitation.household,
        "inviter": invitation.created_by,
        "expires_at": invitation.expires_at,
    }
    subject = render_to_string("accounts/email/invitation_subject.txt", context).strip()
    body = render_to_string("accounts/email/invitation_message.txt", context)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [invitation.email])
