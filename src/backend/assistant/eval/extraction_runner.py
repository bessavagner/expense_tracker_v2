"""Run one model over the receipt dataset. Async, and free of the database.

Deliberately calls ``extraction_agent.run`` rather than ``extract_receipt``:
the harness needs ``result.usage()``, which ``extract_receipt`` drops, and it
must NOT meter into ``UsageRecord`` — a harness run has no household to bill.
The prompt is byte-identical to production's, via ``build_extraction_prompt``.

No database access here: pricing happens in the synchronous layer above. See the
plan's Orientation note on ``sync_to_async`` and connections.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass, replace

from assistant.agents.escalation import should_escalate
from assistant.agents.extraction import (
    ReceiptExtraction,
    build_extraction_prompt,
    extraction_agent,
)
from assistant.agents.model_compat import settings_for
from assistant.eval.dataset import ReceiptCase


@dataclass(frozen=True)
class Attempt:
    """One provider call inside a run: which model, and what it consumed.

    A pipeline run has two of these, on two DIFFERENT models. They cannot be
    priced as one: the whole point of the mix is that the two models cost
    different amounts, so the report prices each attempt against its own
    `ModelPrice` row.
    """

    model: str
    usage: object | None
    latency_ms: int


@dataclass(frozen=True)
class RawRun:
    """One model call: what came back, what it consumed, how long it took."""

    case_id: str
    extraction: ReceiptExtraction | None
    usage: object | None
    latency_ms: int
    error: str
    # True when a pipeline run needed its second attempt. Single-model runs are
    # always False, so the escalation rate is `mean(r.escalated)` over a suite.
    escalated: bool = False
    # Per-attempt breakdown, set only by the pipeline runner. Empty means "one
    # call, priced under the report's own model name" — the single-model case.
    attempts: tuple[Attempt, ...] = ()


async def run_extraction_case(case: ReceiptCase, model) -> RawRun:
    """Read one receipt with ``model``.

    Records failures, never raises them — a provider that refuses one image must
    not abort a 10-case comparison.
    """
    prompt = build_extraction_prompt(
        case.read_images(),
        categories=list(case.categories),
        payment_methods=[p.name for p in case.payment_methods],
    )
    started = time.perf_counter()
    try:
        result = await extraction_agent.run(prompt, model=model, model_settings=settings_for(model))
    except Exception as exc:  # noqa: BLE001 - a failed read is data, not a crash
        return RawRun(
            case_id=case.id,
            extraction=None,
            usage=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=f"{type(exc).__name__}: {exc}",
        )
    return RawRun(
        case_id=case.id,
        extraction=result.output,
        usage=result.usage(),
        latency_ms=int((time.perf_counter() - started) * 1000),
        error="",
    )


async def run_extraction_suite(cases: Sequence[ReceiptCase], model) -> list[RawRun]:
    """Every case, in order.

    Sequential on purpose: parallel calls make the latency column meaningless
    and provoke provider rate limits mid-run.
    """
    return [await run_extraction_case(case, model) for case in cases]


@dataclass(frozen=True)
class _SummedUsage:
    """Both attempts' tokens as one usage object.

    `cost_of` reads `input_tokens` / `output_tokens` / `cache_read_tokens` by
    attribute, and a pipeline that reported only the cheap call's tokens would
    price the retry at zero — making every escalating pipeline look cheaper
    than the model it escalates to.
    """

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0


def _sum_usage(*usages) -> _SummedUsage:
    return _SummedUsage(
        input_tokens=sum(getattr(u, "input_tokens", 0) or 0 for u in usages if u),
        output_tokens=sum(getattr(u, "output_tokens", 0) or 0 for u in usages if u),
        cache_read_tokens=sum(getattr(u, "cache_read_tokens", 0) or 0 for u in usages if u),
    )


def _model_name(model) -> str:
    """The string a `ModelPrice` row is keyed by.

    A model is usually the provider string; under `--stub` it is a `TestModel`
    instance, which has no price and is reported as unpriced rather than as free.
    """
    return model if isinstance(model, str) else type(model).__name__


async def run_pipeline_case(case: ReceiptCase, cheap, strong) -> RawRun:
    """Read one receipt the way production does: cheap first, one escalation.

    Calls the SAME `should_escalate` production calls. A reimplementation here
    would score a pipeline that does not ship, which is the one thing this
    harness exists to prevent.
    """
    first = await run_extraction_case(case, cheap)
    cheap_attempt = Attempt(_model_name(cheap), first.usage, first.latency_ms)
    reason = should_escalate(first.extraction)
    if reason is None:
        return replace(first, attempts=(cheap_attempt,))

    second = await run_extraction_case(case, strong)
    return RawRun(
        case_id=case.id,
        extraction=second.extraction,
        usage=_sum_usage(first.usage, second.usage),
        latency_ms=first.latency_ms + second.latency_ms,
        error=second.error,
        escalated=True,
        attempts=(cheap_attempt, Attempt(_model_name(strong), second.usage, second.latency_ms)),
    )


async def run_pipeline_suite(cases: Sequence[ReceiptCase], cheap, strong) -> list[RawRun]:
    """Every case through the pipeline, in order."""
    return [await run_pipeline_case(case, cheap, strong) for case in cases]
