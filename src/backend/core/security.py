"""Login lockout primitives. No HTTP responses, no Django views — just counting.

``X-Forwarded-For`` is set by the client and only appended to by Google's load
balancer, so the leftmost entry is spoofable and an attacker can rotate it
freely. The IP arm of the lockout is therefore a speed bump; the username arm is
what actually protects an account. Keep both — they fail differently.
"""

import ipaddress
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from core.models import LoginAttempt


def client_ip(request) -> str | None:
    """The best available client address, normalised, or ``None``.

    Returns ``None`` rather than a garbage string when nothing parses, because
    ``LoginAttempt.ip`` is a real ``inet`` column and a malformed value would
    raise at insert time.
    """
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    candidates = [forwarded.split(",")[0].strip(), request.META.get("REMOTE_ADDR")]
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
