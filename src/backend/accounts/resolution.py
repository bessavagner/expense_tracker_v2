"""Which household a person writes into, absent a request.

`accounts.middleware.resolve_active_household` is the *request* answer and
honours the session-selected household. This is the no-request answer: the
oldest membership, which is deterministic because `Membership` orders by
`created_at`. For a multi-household user the two can disagree — a request-
serving path must therefore use the middleware's answer, never this one.
"""

from accounts.migrations_helpers import seed_household_for_user
from accounts.models import Household, Membership


def household_for_user(user):
    """The household ``user`` writes into, creating one if they have none."""
    if user is None:
        return None
    membership = Membership.objects.select_related("household").filter(user=user).first()
    if membership is not None:
        return membership.household
    return seed_household_for_user(Household, Membership, user)
