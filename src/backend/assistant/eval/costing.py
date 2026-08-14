"""What a harness run cost, in tokens, dollars and milliseconds.

Reuses ``assistant.pricing.cost_usd_for`` rather than re-deriving prices: the
comparison table and the operator's production cost report must agree, and two
implementations of the same arithmetic eventually will not.

Deliberately NOT written to ``UsageRecord``. A harness run has no household, and
a cost row nobody can be charged for pollutes the ledger the pricing decisions
are made from.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from assistant.pricing import cost_usd_for


@dataclass(frozen=True)
class CallCost:
    """One provider call inside the harness."""

    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: Decimal | None


def cost_of(model: str, usage, latency_ms: int) -> CallCost:
    """Price one call. ``usage=None`` means the call failed before reporting any.

    Synchronous and hits the database (``ModelPrice``). Call it from the command,
    never from inside an async runner.
    """
    inp = int(getattr(usage, "input_tokens", 0) or 0) if usage is not None else 0
    out = int(getattr(usage, "output_tokens", 0) or 0) if usage is not None else 0
    cost = cost_usd_for(model, usage) if usage is not None else None
    return CallCost(
        model=model,
        input_tokens=inp,
        output_tokens=out,
        latency_ms=latency_ms,
        cost_usd=cost,
    )


@dataclass(frozen=True)
class CostTotals:
    """What a whole suite cost on one model."""

    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    unpriced_calls: int
    latency_ms_total: int

    @property
    def avg_latency_ms(self) -> int:
        return int(self.latency_ms_total / self.calls) if self.calls else 0


def total(costs: Iterable[CallCost]) -> CostTotals:
    """Sum the priced calls; count the unpriced ones apart."""
    costs = list(costs)
    priced = [c.cost_usd for c in costs if c.cost_usd is not None]
    return CostTotals(
        calls=len(costs),
        input_tokens=sum(c.input_tokens for c in costs),
        output_tokens=sum(c.output_tokens for c in costs),
        cost_usd=sum(priced, Decimal("0")),
        unpriced_calls=sum(1 for c in costs if c.cost_usd is None),
        latency_ms_total=sum(c.latency_ms for c in costs),
    )
