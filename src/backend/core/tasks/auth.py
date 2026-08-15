"""Prove an inbound /tasks/ request really came from Cloud Tasks.

This service runs with ``--allow-unauthenticated`` because it is a public web
app, so Cloud Run will not verify the token for us — the check has to happen
here. Without it, ``/tasks/<name>/`` is an unauthenticated RPC endpoint that
any stranger can drive, with the application's own database behind it.

Fails closed: with no service account configured, every request is refused. An
endpoint that silently accepts everything when a setting is missing is worse
than one that is switched off, because nothing about it looks wrong.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

BEARER_PREFIX = "Bearer "


def _google_verifier(token: str, audience: str) -> dict:
    """The real check. Isolated so no test needs a network round trip.

    Imported inside the function so that ``google-auth`` is not required to
    import this module — a developer with CLOUD_TASKS_ENABLED=0 never reaches
    this line.
    """
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, google_requests.Request(), audience)


# Module-level so a test can replace it. Replacing the object rather than
# wrapping it is what makes the patch total — the same trick `conftest.py`
# uses for `assistant.services.embedding.async_client`.
verify_id_token = _google_verifier


def rejection_reason(request) -> str | None:
    """``None`` when the request is a genuine Cloud Tasks dispatch.

    Returns a short reason otherwise. The caller logs it and never returns it
    to the client: telling an attacker *which* check failed is free help.
    """
    expected = settings.CLOUD_TASKS_OIDC_SERVICE_ACCOUNT
    if not expected:
        return "no service account configured"

    header = request.headers.get("Authorization", "")
    if not header.startswith(BEARER_PREFIX):
        return "missing bearer token"

    token = header[len(BEARER_PREFIX) :].strip()
    if not token:
        return "empty bearer token"

    try:
        claims = verify_id_token(token, settings.CLOUD_TASKS_AUDIENCE)
    except Exception as exc:
        # Broad on purpose: google-auth raises several unrelated exception
        # types for "this token is not good", and every one of them means the
        # same thing here.
        return f"token rejected: {type(exc).__name__}"

    if claims.get("email") != expected:
        return "wrong service account"
    # Checked separately from the address: an unverified email claim means
    # Google is not vouching for the identity, which makes the address match
    # worth nothing.
    if claims.get("email_verified") is not True:
        return "unverified service account email"
    return None
