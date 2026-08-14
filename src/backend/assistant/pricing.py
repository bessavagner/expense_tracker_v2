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
    if key not in _cache:
        _cache[key] = (
            ModelPrice.objects.filter(model_name=model_name, effective_from__lte=on)
            .order_by("-effective_from")
            .first()
        )
    return _cache[key]


def cost_usd_for(model_name: str, usage) -> Decimal | None:
    """USD cost of one call, or ``None`` when the model has no price row.

    ``None`` rather than ``Decimal(0)`` on purpose: zero is indistinguishable
    from a genuinely free call, and an unpriced model silently metering at zero
    is exactly how a cost report becomes fiction. The report counts nulls and
    says so.
    """
    price = price_for(model_name)
    if price is None:
        return None
    inp = Decimal(getattr(usage, "input_tokens", 0) or 0)
    out = Decimal(getattr(usage, "output_tokens", 0) or 0)
    total = (inp / MILLION) * price.input_per_mtok + (out / MILLION) * price.output_per_mtok
    return total.quantize(QUANTUM)
