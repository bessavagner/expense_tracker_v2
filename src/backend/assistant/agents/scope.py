"""What the agent is allowed to see, and who is asking.

`deps_type` was the acting `User`, which conflated two questions the tenancy
split apart: *whose data* (the household) and *who wrote this row*
(`created_by`, and the throttle's actor). Frozen, because a tool body runs on
LLM-chosen arguments and must not be able to widen its own scope.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentScope:
    """The household a tool may read, and the person on the other end."""

    household: object | None
    user: object
    # The UsageInteraction this run belongs to, so a tool that makes its own
    # provider call (check_memory → get_embedding) can attribute its cost to
    # the same user action. Threaded explicitly rather than via a ContextVar:
    # the SSE generator is iterated by ASGI in a different context from the
    # view that built it, so a ContextVar set in the view would not be visible.
    interaction: object | None = None

    @classmethod
    def for_request(cls, request):
        """Build a scope from a request the middleware has already seen.

        `getattr` rather than `request.household`: a request built without the
        middleware must fail closed to `None` — which every scoped queryset
        turns into `none()` — rather than raise.
        """
        return cls(household=getattr(request, "household", None), user=request.user)
