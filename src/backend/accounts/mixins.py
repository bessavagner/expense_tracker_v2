"""View-layer entry point to household scoping.

Both Django's generic CBVs and DRF's generics funnel through
``get_queryset()``, so one mixin covers the HTMX views and the dashboard API.
"""

from accounts.scoping import HouseholdScopedQuerySet


class HouseholdScopedMixin:
    """Scope a view's queryset to ``request.household``.

    Raises rather than degrading: a view that mixes this in but points at a
    model without the scoped manager is a bug, and a silently unscoped
    queryset is the exact failure this epic exists to prevent.
    """

    def get_queryset(self):
        if hasattr(super(), "get_queryset"):
            queryset = super().get_queryset()
        else:
            queryset = self.model._default_manager.all()
        if not isinstance(queryset, HouseholdScopedQuerySet):
            raise TypeError(
                f"{queryset.model.__name__} is not household-scoped: give it "
                "HouseholdScopedManager before using HouseholdScopedMixin."
            )
        return queryset.for_request(self.request)
