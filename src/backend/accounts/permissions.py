"""Which member may do what.

E04 settled on two roles deliberately: an owner may invite and remove people,
a member may only edit the ledger. That rule is written here once so the views
ask rather than restate it.
"""

from django.core.exceptions import PermissionDenied

from accounts.models import Membership, Role


def is_owner(user, household) -> bool:
    """True when ``user`` owns ``household``.

    Fails closed on every missing input: an unauthenticated user, an
    unresolved household, or a membership in some *other* household are all
    "no", and none of them raise. A permission check that raises on absent
    input becomes a 500 on the exact request that should have been a 403.
    """
    if user is None or household is None or not getattr(user, "is_authenticated", False):
        return False
    return Membership.objects.filter(user=user, household=household, role=Role.OWNER).exists()


class OwnerRequiredMixin:
    """Refuse the request unless it comes from an owner of its own household.

    Reads ``request.household``, which ``accounts.middleware`` has already
    resolved and validated against the user's memberships — so this never has
    to re-derive the tenant, and cannot disagree with the rest of the request.

    Raises ``PermissionDenied`` rather than redirecting: the caller is signed
    in and simply may not do this, and bouncing them to a login page they are
    already past is the confusing answer.
    """

    def dispatch(self, request, *args, **kwargs):
        if not is_owner(getattr(request, "user", None), getattr(request, "household", None)):
            raise PermissionDenied("Somente o dono da casa pode fazer isso.")
        return super().dispatch(request, *args, **kwargs)
