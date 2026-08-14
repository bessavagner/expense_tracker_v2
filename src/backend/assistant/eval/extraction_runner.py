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
from dataclasses import dataclass

from assistant.agents.extraction import (
    ReceiptExtraction,
    build_extraction_prompt,
    extraction_agent,
)
from assistant.eval.dataset import ReceiptCase


@dataclass(frozen=True)
class RawRun:
    """One model call: what came back, what it consumed, how long it took."""

    case_id: str
    extraction: ReceiptExtraction | None
    usage: object | None
    latency_ms: int
    error: str


async def run_extraction_case(case: ReceiptCase, model) -> RawRun:
    """Read one receipt with ``model``.

    Records failures, never raises them — a provider that refuses one image must
    not abort a 10-case comparison.
    """
    data, media_type = case.read_image()
    prompt = build_extraction_prompt(
        [(data, media_type)],
        categories=list(case.categories),
        payment_methods=[p.name for p in case.payment_methods],
    )
    started = time.perf_counter()
    try:
        result = await extraction_agent.run(prompt, model=model)
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
