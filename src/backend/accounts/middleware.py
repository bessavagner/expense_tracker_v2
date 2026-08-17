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


#: Prefixes the redirect never touches. Everything here either has no user
#: interface to redirect (the API, the health check, the task dispatcher), or
#: redirecting it would break something worse than an unonboarded dashboard
#: (the setup flow itself would loop; logout would become unreachable).
#:
#: The admin console is deliberately NOT here, even though staff have no
#: household-onboarding concept. `settings.ADMIN_URL_PATH` is a secret the
#: product hides by making its 404 indistinguishable from a wrong guess
#: (`core.admin_gate`, and the settings.py comment above `ADMIN_URL_PATH`
#: documents the prior incident). A path-prefix exemption would reopen that
#: oracle: the real path would answer 404 (exempt, gate raises) while every
#: wrong guess answered 302-to-onboarding (not exempt, this middleware
#: redirects) for any authenticated user whose household is unonboarded — a
#: class that includes every new signup. Staff are exempted by identity below
#: instead.
_ONBOARDING_EXEMPT_PREFIXES = (
    "/casa/comecar/",
    "/api/",
    "/accounts/",
    "/tasks/",
    "/healthz/",
    "/static/",
    "/sw.js",
    "/offline/",
    "/manifest.webmanifest",
    "/.well-known/",
    # E13. Every new signup has an unonboarded household, and every new signup
    # is exactly who clicks these links from the form they are filling in.
    "/privacidade/",
    "/termos/",
)


def onboarding_redirect_middleware(get_response):
    """Send a household that has not been through setup to the setup.

    Runs after `active_household_middleware`, because it needs
    `request.household`. Deliberately narrow:

    * only GET — a POST redirected loses its body, and a 302 on a form
      submission is indistinguishable from the form having worked;
    * never HTMX — HTMX swaps a redirect's *body* into whatever target the
      fragment named, which would paint the whole setup page inside a table
      cell rather than navigating;
    * never staff — the admin console has nothing to do with a household's
      setup, and exempting it by path instead would reopen the secret-path
      oracle `core.admin_gate` exists to close (see the comment on
      `_ONBOARDING_EXEMPT_PREFIXES`). This also covers `createsuperuser`,
      whose account holds no `Membership` and so would otherwise be routed
      into a setup flow for a household it did not mean to create;
    * never the exempt prefixes above.

    One query per request, and only for a household that has not finished —
    `OnboardingState.is_complete` walks `steps_done` in Python, so the row is
    still fetched on every non-exempt GET; there is no query-level
    short-circuit on `completed_at`.
    """
    from django.http import HttpResponseRedirect
    from django.urls import reverse

    from accounts.models import OnboardingState

    def middleware(request):
        if (
            request.method == "GET"
            and getattr(request, "household", None) is not None
            and not request.user.is_staff
            and not request.headers.get("HX-Request")
            and not request.path.startswith(_ONBOARDING_EXEMPT_PREFIXES)
        ):
            state = OnboardingState.for_household(request.household)
            if not state.is_complete:
                return HttpResponseRedirect(reverse("onboarding"))
        return get_response(request)

    return middleware
