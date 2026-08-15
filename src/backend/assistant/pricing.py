"""Per-model prices and the USD cost of one provider call.

The cache exists because the quota chokepoint and every metered call site would
otherwise issue a query per call. Prices change a few times a year, so a
process-lifetime cache invalidated on write is the right trade — see
``clear_price_cache``, wired to ``post_save``/``post_delete`` below.
"""

from datetime import date
from decimal import Decimal

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from assistant.models import ModelPrice

MILLION = Decimal(1_000_000)
# Six places: a cheap model at a few hundred tokens costs less than a
# micro-dollar, and rounding those to zero across thousands of calls is how a
# cost report ends up lying.
QUANTUM = Decimal("0.000001")

_cache: dict[tuple[str, date], "ModelPrice | None"] = {}


def clear_price_cache() -> None:
    """Drop the memoised lookups. Called on any ``ModelPrice`` write."""
    _cache.clear()


@receiver(post_save, sender=ModelPrice)
@receiver(post_delete, sender=ModelPrice)
def _invalidate(sender, **kwargs):
    clear_price_cache()


def price_for(model_name: str, *, on: date | None = None) -> ModelPrice | None:
    """The price row in force for ``model_name`` on ``on`` (default: today)."""
    on = on or timezone.localdate()
    key = (model_name, on)
    if key in _cache:
        return _cache[key]
    # Returned from a local, never re-read out of the dict: `clear_price_cache`
    # runs from a `post_save` signal in whatever thread saved a `ModelPrice`,
    # so it can land between the write below and a second read. That read would
    # raise KeyError into `record_usage`, which reports rather than raises — and
    # the visible symptom would be a cost row that silently never appeared.
    result = (
        ModelPrice.objects.filter(model_name=model_name, effective_from__lte=on)
        .order_by("-effective_from")
        .first()
    )
    _cache[key] = result
    return result


def cost_usd_for(model_name: str, usage) -> Decimal | None:
    """USD cost of one call, or ``None`` when the model has no price row.

    ``None`` rather than ``Decimal(0)`` on purpose: zero is indistinguishable
    from a genuinely free call, and an unpriced model silently metering at zero
    is exactly how a cost report becomes fiction. The report counts nulls and
    says so.

    Cache reads are billed apart (D03). ``input_tokens`` INCLUDES
    ``cache_read_tokens`` — they are a subset of the prompt, not a second
    bucket — so the fresh half is the difference, and pricing the whole prompt
    at the full rate over-reported by roughly 4x on a repeated workload.
    """
    price = price_for(model_name)
    if price is None:
        return None
    inp = Decimal(getattr(usage, "input_tokens", 0) or 0)
    out = Decimal(getattr(usage, "output_tokens", 0) or 0)
    # Clamped because a negative fresh half would UNDER-state the bill, and
    # under-stating is the one direction that is unsafe here.
    cached = min(Decimal(getattr(usage, "cache_read_tokens", 0) or 0), inp)
    # A row with no cached rate bills cache reads at the full input rate: the
    # old behaviour, which errs high rather than inventing a discount.
    cached_rate = price.cached_input_per_mtok
    if cached_rate is None:
        cached_rate = price.input_per_mtok
    total = (
        ((inp - cached) / MILLION) * price.input_per_mtok
        + (cached / MILLION) * cached_rate
        + (out / MILLION) * price.output_per_mtok
    )
    return total.quantize(QUANTUM)
