"""The one thing E13 adds to the signup form.

Wired through ``ACCOUNT_SIGNUP_FORM_CLASS`` rather than by replacing allauth's
form: allauth makes the named class the *base* of both its local and its social
signup forms (``allauth/account/internal/flows/signup.py``), so this is the
extension point that does not fork a security-critical flow. Subclassing
``allauth.account.forms.SignupForm`` here would make it its own base and fail
at import.

``signup`` runs after ``adapter.save_user``, so ``user`` already has a primary
key — which is why the acceptance rows can be written straight in.
"""

from django import forms
from django.conf import settings

from core.models import PolicyAcceptance, PolicyDocument


def client_ip(request) -> str | None:
    """The caller's address as Cloud Run reports it.

    Cloud Run terminates TLS at the front end and puts the real client first in
    ``X-Forwarded-For``; ``REMOTE_ADDR`` is the proxy. Taking the first element
    is right here and would be wrong for rate limiting, where a spoofed header
    is the attack — this value is evidence attached to a consent, not a control.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


class LedgerSignupForm(forms.Form):
    """One required checkbox, and the two rows it produces."""

    accept_terms = forms.BooleanField(
        required=True,
        label="Li e aceito os Termos de Uso e o Aviso de Privacidade",
        error_messages={
            "required": "Para criar a conta é preciso aceitar os Termos de Uso "
            "e o Aviso de Privacidade."
        },
    )

    def signup(self, request, user) -> None:
        """Record what was accepted, at the version live right now.

        Two rows rather than one: the documents are versioned independently, so
        a change to the terms must not silently claim a fresh acceptance of the
        privacy notice.
        """
        ip = client_ip(request)
        PolicyAcceptance.objects.bulk_create(
            [
                PolicyAcceptance(
                    user=user,
                    document=PolicyDocument.PRIVACY,
                    version=settings.PRIVACY_POLICY_VERSION,
                    ip=ip,
                ),
                PolicyAcceptance(
                    user=user,
                    document=PolicyDocument.TERMS,
                    version=settings.TERMS_VERSION,
                    ip=ip,
                ),
            ],
            # A retried signup must not 500 on the unique constraint.
            ignore_conflicts=True,
        )
