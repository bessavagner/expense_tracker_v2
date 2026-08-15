"""The only writer of ``UsageRecord``.

One rule governs this module: **metering never fails a user's request.** A
broken cost ledger is an operations problem; a chat turn that 500s because the
cost ledger was broken is a customer problem. So every write is wrapped, and a
failure is reported to Sentry rather than raised (E06 S06-4 — silent is worse
than loud, but loud must not mean broken).
"""

import logging
import time

import sentry_sdk
from asgiref.sync import sync_to_async

from assistant.models import UsageRecord
from assistant.pricing import cost_usd_for

logger = logging.getLogger(__name__)


class Timer:
    """Wall-clock milliseconds around a call.

    ``perf_counter`` rather than ``time.time``: latency must not go negative
    because NTP stepped the clock mid-request.
    """

    def __init__(self):
        self.ms = 0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = int((time.perf_counter() - self._start) * 1000)
        return False


async def record_usage(
    *,
    household,
    kind: str,
    model: str,
    latency_ms: int,
    ok: bool,
    interaction=None,
    user=None,
    usage=None,
    escalation_reason: str = "",
) -> None:
    """Persist one provider call. Never raises.

    ``usage`` is any object exposing ``input_tokens`` / ``output_tokens`` —
    PydanticAI's ``RunUsage`` is the usual one. ``None`` (a call that failed
    before returning usage) records the attempt with null tokens and null cost,
    because a failed vision call still costs money (S07-2).

    ``escalation_reason`` is blank for a first attempt and names the signal that
    triggered a second one (E09 S09-3). A failed escalation still carries its
    reason: it cost money and it counts against the escalation rate.
    """
    try:
        # `cost_usd_for` reads `ModelPrice` on a cache miss, and a synchronous
        # ORM call inside a coroutine raises SynchronousOnlyOperation. That
        # exception would land in the `except` below and be *reported* rather
        # than raised, so the symptom is not a crash — it is a cost ledger that
        # silently stays empty. Hence the explicit hop, cache hit or not.
        cost = await sync_to_async(cost_usd_for)(model, usage) if usage is not None else None
        await UsageRecord.objects.acreate(
            interaction=interaction,
            household=household,
            user=user,
            kind=kind,
            model=model,
            input_tokens=getattr(usage, "input_tokens", None) if usage else None,
            cache_read_tokens=getattr(usage, "cache_read_tokens", None) if usage else None,
            output_tokens=getattr(usage, "output_tokens", None) if usage else None,
            cost_usd=cost,
            latency_ms=latency_ms,
            ok=ok,
            escalation_reason=escalation_reason,
        )
    except Exception:
        # Deliberately does not re-raise. See the module docstring.
        sentry_sdk.capture_exception()
        logger.warning("Failed to record usage for model=%s kind=%s", model, kind)
