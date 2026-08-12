"""Resolve the request's active household exactly once, before any view runs.

Decision 1 of the epic: a user may belong to several households, but works in
one at a time. The choice lives in the session; the *validation* of that
choice lives here, because a session value is user-controlled input.
"""

from django.core.exceptions import ValidationError

from accounts.models import Membership

ACTIVE_HOUSEHOLD_SESSION_KEY = "active_household_id"


def resolve_active_household(request):
    """The household this request operates in, or ``None``.

    Never trusts the session id on its own: it is only honoured when the
    user actually holds a membership in that household. Otherwise falls back
    to the oldest membership, which is deterministic because ``Membership``
    orders by ``created_at``.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None

    memberships = Membership.objects.filter(user=user).select_related("household")

    chosen_id = request.session.get(ACTIVE_HOUSEHOLD_SESSION_KEY)
    if chosen_id:
        try:
            chosen = memberships.filter(household_id=chosen_id).first()
        except (ValidationError, ValueError):
            # The session value is user-controlled: a tampered cookie must
            # fall back to the default household, not raise a 500.
            chosen = None
        if chosen is not None:
            return chosen.household

    fallback = memberships.first()
    return fallback.household if fallback is not None else None


def active_household_middleware(get_response):
    def middleware(request):
        household = resolve_active_household(request)
        request.household = household
        if household is not None:
            # Only write when it actually changes — assigning marks the
            # session modified, and that is a session-store round trip on
            # every single request.
            household_id = str(household.id)
            if request.session.get(ACTIVE_HOUSEHOLD_SESSION_KEY) != household_id:
                request.session[ACTIVE_HOUSEHOLD_SESSION_KEY] = household_id
        return get_response(request)

    return middleware
