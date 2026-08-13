"""The only thing standing between the open internet and every household's money.

404 rather than 403, everywhere. A 403 tells an unauthenticated scanner that
the path it guessed is the admin; a 404 tells it nothing, which is the whole
value of moving the path in the first place. The two controls are independent
on purpose — guessing the path correctly still gets you nothing, and being
staff on the wrong path still gets you nothing.
"""

from django.conf import settings
from django.http import Http404, HttpResponseRedirect

from core.security import client_ip


def _admin_prefix() -> str:
    return "/" + settings.ADMIN_URL_PATH.lstrip("/")


def _has_second_factor(user) -> bool:
    from allauth.mfa.utils import is_mfa_enabled

    return is_mfa_enabled(user)


def admin_staff_only_middleware(get_response):
    """Refuse admin to everyone but staff carrying a second factor.

    Must run after `AuthenticationMiddleware` — it reads `request.user`.
    """

    def middleware(request):
        prefix = _admin_prefix()
        if not request.path.startswith(prefix):
            return get_response(request)

        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or not user.is_staff:
            # Anonymous and ordinary users are told the path does not exist,
            # which — as far as they are concerned — is true.
            raise Http404

        if not _has_second_factor(user):
            # Staff, but unarmed. 404ing here would lock the only operator out
            # of their own admin with no explanation, which is how this gets
            # reverted at 2am. Send them to enrol instead.
            from django.urls import reverse

            return HttpResponseRedirect(reverse("mfa_activate_totp"))

        from core.models import AdminAccessLog

        AdminAccessLog.objects.create(
            actor=user,
            path=request.path[:500],
            method=request.method,
            ip=client_ip(request),
        )
        return get_response(request)

    return middleware
