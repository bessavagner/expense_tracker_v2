"""Resolve the request's active household exactly once, before any view runs.

Decision 1 of the epic: a user may belong to several households, but works in
one at a time. The choice lives in the session; the *validation* of that
choice lives here, because a session value is user-controlled input.
"""

from django.core.exceptions import ValidationError

from accounts.models import Membership
from accounts.resolution import household_for_user

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
    if fallback is not None:
        return fallback.household

    # No membership at all. `createsuperuser` and the Django admin both create
    # users this way, and the runbook tells the operator to run the former
    # right after deploying. Phase 4 deleted accounts/bridge.py, whose
    # `household_for_writer` minted such a user their own household on first
    # write, and made `household` NOT NULL in the same commit — so without this
    # fallback every write they attempt is an unhandled 500 on a NOT NULL
    # violation, while every read fails closed to none() and looks merely empty.
    #
    # Giving them their own household is the fail-closed answer, and the same
    # rule accounts/0003 seeded with. Borrowing an existing one would be the
    # leak. `household_for_user` is idempotent, and this branch is only reached
    # for a user who has no membership, so it costs no query in the normal case.
    return household_for_user(user)


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
