"""Login lockout primitives. No HTTP responses, no Django views — just counting.

Behind Google's load balancer, ``X-Forwarded-For`` arrives as
``<client-supplied>, <real-client>, <lb>``: GCP appends exactly two entries —
the real client address, then its own — so only the second-from-right entry is
trustworthy. Everything left of it, including the leftmost entry, is supplied
by the client and forgeable. Trusting the leftmost entry would not just let an
attacker evade their own IP arm (a tolerable weakening down to the username
arm); it would let an unauthenticated attacker claim to be *any* address,
including a real user's, and burn that user's lockout budget by proxy — an
availability attack aimed at a chosen victim. See ``client_ip`` for how the
trustworthy entry is picked.
"""

import ipaddress
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from core.models import LoginAttempt


def client_ip(request) -> str | None:
    """The real client address behind the GCP load balancer, or ``None``.

    Picks the second-from-right ``X-Forwarded-For`` entry — the one GCP itself
    appended — rather than the leftmost, client-supplied one. Falls back to
    ``REMOTE_ADDR`` when the header doesn't have that shape (fewer than two
    entries, e.g. local dev with no load balancer in front, or the trusted
    entry itself failing to parse).

    Returns ``None`` rather than a garbage string when nothing parses, because
    ``LoginAttempt.ip`` is a real ``inet`` column and a malformed value would
    raise at insert time.
    """
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    parts = [part.strip() for part in forwarded.split(",") if part.strip()]
    candidates = []
    if len(parts) >= 2:
        candidates.append(parts[-2])
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
