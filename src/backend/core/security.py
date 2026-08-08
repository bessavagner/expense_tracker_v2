"""Login lockout primitives. No HTTP responses, no Django views — just counting.

This service (Cloud Run project ``expense-tracker-482807``) takes traffic
directly at its ``run.app`` URL — ingress is ``all`` and there is no GCP
external HTTP(S) load balancer in front of it (no url-maps, no forwarding
rules, Compute Engine unused in the project). Cloud Run's own front end
appends exactly one entry to ``X-Forwarded-For``: the real client address, at
the end. So the trustworthy entry is the *last* one, not the leftmost —
everything before it is supplied by the client and forgeable. Trusting the
leftmost entry would not just let an attacker evade their own IP arm (a
tolerable weakening down to the username arm); it would let an
unauthenticated attacker claim to be *any* address, including a real user's,
and burn that user's lockout budget by proxy — an availability attack aimed
at a chosen victim. See ``client_ip`` for how the trustworthy entry is
picked, and for what changes if a load balancer is ever added in front of
this service.
"""

import ipaddress
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from core.models import LoginAttempt


def client_ip(request) -> str | None:
    """The real client address behind Cloud Run's own front end, or ``None``.

    Picks the *last* ``X-Forwarded-For`` entry, because Cloud Run's front end
    appends the real client IP and nothing else runs in front of it: with no
    header the request came straight in (use ``REMOTE_ADDR``); with a
    client-supplied header, Cloud Run appends the real IP after whatever the
    client sent, so the last entry is always the trustworthy one. A client
    cannot append after Cloud Run's front end.

    If a load balancer is ever put in front of this service, this changes:
    a GCP external HTTP(S) load balancer appends its *own* address after the
    real client IP, making the trustworthy entry the second-from-right one
    instead — update this function (and the note in ``docs/runbook.md``) if
    that ever happens.

    Returns ``None`` rather than a garbage string when nothing parses, because
    ``LoginAttempt.ip`` is a real ``inet`` column and a malformed value would
    raise at insert time.
    """
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    parts = [part.strip() for part in forwarded.split(",") if part.strip()]
    candidates = []
    if parts:
        candidates.append(parts[-1])
    candidates.append(request.META.get("REMOTE_ADDR"))
    for candidate in candidates:
        try:
            return str(ipaddress.ip_address(candidate))
        except (TypeError, ValueError):
            continue
    return None


def is_locked(username: str | None, ip: str | None, *, now: datetime | None = None) -> bool:
    """True when this username OR this IP has burned the failure budget."""
    if not username and not ip:
        return False
    now = now or timezone.now()
    since = now - timedelta(minutes=settings.LOGIN_FAILURE_WINDOW_MINUTES)
    limit = settings.LOGIN_FAILURE_LIMIT
    recent = LoginAttempt.objects.filter(created_at__gte=since)
    if username and recent.filter(username=username).count() >= limit:
        return True
    return bool(ip and recent.filter(ip=ip).count() >= limit)
