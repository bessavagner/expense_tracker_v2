"""Per-account rate limiting for the assistant endpoint.

Why not DRF throttling: ``chat_view`` is a plain async Django view returning a
``StreamingHttpResponse``. DRF's throttle classes hang off ``APIView`` and DRF
has no async view support, so adopting them means rewriting the streaming
endpoint — exactly the risk R0 exists to avoid.

Why not middleware: the image budget is tighter than the text budget, so a
middleware would have to parse the multipart body to tell them apart, before the
view parses it again. Calling the guard from ``chat_view`` keeps the "no model
call before the check" guarantee visible where a reviewer reads it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from assistant.models import AssistantUsageEvent, AssistantUsageKind

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


@dataclass(frozen=True)
class ThrottleRule:
    limit: int
    window: timedelta
    label: str  # pt-BR noun for the user-facing message


def rules_for(kind: str) -> list[ThrottleRule]:
    """The rules that apply to ``kind``, hourly first.

    Read from settings on every call rather than captured at import time, so the
    ``settings`` fixture can override them in tests and an env change takes
    effect on the next deploy without a code change.
    """
    if kind == AssistantUsageKind.IMAGE:
        return [
            ThrottleRule(settings.ASSISTANT_THROTTLE_IMAGE_PER_HOUR, HOUR, "hora"),
            ThrottleRule(settings.ASSISTANT_THROTTLE_IMAGE_PER_DAY, DAY, "dia"),
        ]
    return [
        ThrottleRule(settings.ASSISTANT_THROTTLE_TEXT_PER_HOUR, HOUR, "hora"),
        ThrottleRule(settings.ASSISTANT_THROTTLE_TEXT_PER_DAY, DAY, "dia"),
    ]


async def exceeded_rule(user, kind: str, *, now: datetime | None = None) -> ThrottleRule | None:
    """The first rule this user has already met, or ``None`` when clear.

    "Met", not "exceeded": a user who has spent exactly ``limit`` turns in the
    window is done, because the turn being checked would be number ``limit + 1``.
    """
    now = now or timezone.now()
    for rule in rules_for(kind):
        used = await AssistantUsageEvent.objects.filter(
            user=user, kind=kind, created_at__gte=now - rule.window
        ).acount()
        if used >= rule.limit:
            return rule
    return None
