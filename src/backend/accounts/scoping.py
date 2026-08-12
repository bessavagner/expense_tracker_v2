"""The one supported way to scope a query to a household.

Global constraint 4 of the backlog: after E04, no epic may write
``filter(user=...)`` on a domain model. Everything goes through here, so
there is one class to review and one class to test exhaustively.
"""

from django.db import models


class HouseholdScopedQuerySet(models.QuerySet):
    """A queryset over a model carrying ``household``."""

    def for_household(self, household):
        """Rows belonging to ``household``.

        A falsy household yields ``none()`` — never the full table. An
        unresolved tenant must fail closed: the alternative is that one
        missing middleware turns every list view into a data leak.
        """
        if household is None:
            return self.none()
        return self.filter(household=household)

    def for_request(self, request):
        """Rows belonging to the request's active household.

        Uses ``getattr`` rather than ``request.household`` so that a request
        built without the middleware (a bare ``RequestFactory``, a management
        command) fails closed instead of raising.
        """
        return self.for_household(getattr(request, "household", None))


HouseholdScopedManager = models.Manager.from_queryset(HouseholdScopedQuerySet)
