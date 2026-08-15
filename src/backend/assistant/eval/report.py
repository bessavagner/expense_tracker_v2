"""Turn raw runs into the comparison table the model decision is made from.

Written to a file as well as stdout so runs are diffable over time: the point of
a baseline is that next quarter's number can be subtracted from this one.

A case that errored is reported as a scored failure, never dropped. A dropped
failure makes a broken model look like a small dataset.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from assistant.eval.behaviour import BehaviourCase, score_ledger
from assistant.eval.costing import CostTotals, cost_of, total
from assistant.eval.dataset import ReceiptCase
from assistant.eval.extraction_runner import Attempt
from assistant.eval.scoring import aggregate_extraction, score_extraction


@dataclass(frozen=True)
class ModelReport:
    """One model, one suite, everything the comparison table shows."""

    model: str
    suite: str
    n: int
    overall: float
    dimensions: dict[str, float]
    totals: CostTotals
    failures: tuple[str, ...]


def build_extraction_report(model: str, cases: Sequence[ReceiptCase], runs) -> ModelReport:
    """Score every extraction run and price every call."""
    by_id = {c.id: c for c in cases}
    scores, costs, failures = [], [], []
    for run in runs:
        # A pipeline run carries its attempts, on two different models. Pricing
        # them under the report's own label would find no `ModelPrice` row and
        # report the whole pipeline at $0 — which reads as free and is the exact
        # number the E09 cost gate turns on.
        for attempt in getattr(run, "attempts", ()) or [Attempt(model, run.usage, run.latency_ms)]:
            costs.append(cost_of(attempt.model, attempt.usage, attempt.latency_ms))
        if run.error or run.extraction is None:
            failures.append(f"{run.case_id}: {run.error or 'no output'}")
            continue
        score = score_extraction(by_id[run.case_id], run.extraction)
        scores.append(score)
        if score.overall < 1.0:
            detail = []
            if not score.money_ok:
                detail.append("money invariant FAILED")
            if score.missed:
                detail.append(f"missed {len(score.missed)}")
            if score.spurious:
                detail.append(f"spurious {len(score.spurious)}")
            failures.append(f"{run.case_id}: {', '.join(detail) or 'partial'}")

    agg = aggregate_extraction(scores)
    n = len(runs)
    # Errored runs score zero and still count, so the denominator is every case
    # attempted rather than only the ones that came back. The dimensions get the
    # SAME denominator: `aggregate_extraction` only ever sees the runs that
    # returned, so a model that answered one receipt out of seven perfectly
    # would otherwise print 1.00 across every column next to a score of 0.14 —
    # observed live with `qwen3.7-flash`, and it reads as the best model in the
    # table.
    answered = (len(scores) / n) if n else 0.0
    overall = round(agg.overall * answered, 6) if n else 0.0

    def _scaled(value: float) -> float:
        return round(value * answered, 6)

    return ModelReport(
        model=model,
        suite="extraction",
        n=n,
        overall=overall,
        dimensions={
            "money_ok_rate": _scaled(agg.money_ok_rate),
            "item_recall": _scaled(agg.item_recall),
            "item_precision": _scaled(agg.item_precision),
            "amount_accuracy": _scaled(agg.amount_accuracy),
            "category_accuracy": _scaled(agg.category_accuracy),
            "store_accuracy": _scaled(agg.store_accuracy),
            "date_accuracy": _scaled(agg.date_accuracy),
        },
        totals=total(costs),
        failures=tuple(failures),
    )


def build_behaviour_report(model: str, cases: Sequence[BehaviourCase], runs) -> ModelReport:
    """Score every behavioural run against its expected ledger.

    A behavioural case is several turns, and only the case as a whole is timed —
    the runner cannot bill each turn separately. The whole run's latency is
    therefore charged to its FIRST call rather than recorded as an extra
    zero-token call of its own: an invented call would be counted as unpriced
    forever, and the table would warn about a missing `ModelPrice` that exists.
    """
    by_id = {c.id: c for c in cases}
    scores, costs, failures = [], [], []
    for run in runs:
        # `[None]` for a run that died before any turn reported usage: the
        # attempt still happened and still belongs in the call count.
        usages = list(run.usages) or [None]
        for i, usage in enumerate(usages):
            costs.append(cost_of(model, usage, run.latency_ms if i == 0 else 0))
        if run.error:
            failures.append(f"{run.case_id}: {run.error}")
            scores.append(0.0)
            continue
        score = score_ledger(by_id[run.case_id], run.rows)
        scores.append(score.score)
        if not score.passed:
            failures.append(f"{run.case_id}: {'; '.join(score.errors)}")

    n = len(runs)
    return ModelReport(
        model=model,
        suite="behaviour",
        n=n,
        overall=round(sum(scores) / n, 6) if n else 0.0,
        dimensions={"cases_passed": float(sum(1 for s in scores if s == 1.0))},
        totals=total(costs),
        failures=tuple(failures),
    )


def _fmt(value: float) -> str:
    return f"{value:.2f}"


def render_markdown(
    reports: Sequence[ModelReport], *, generated_at: str, skipped: Sequence[str] = ()
) -> str:
    """The human-readable comparison. One table per suite."""
    lines = [
        "# Model evaluation (E08)",
        "",
        f"Generated: {generated_at}",
        "",
    ]
    if skipped:
        lines += [
            f"> **{len(skipped)} case(s) skipped** — image not found. Set "
            "`EVAL_FIXTURES_DIR` (see `docs/eval-dataset.md`): " + ", ".join(skipped),
            "",
        ]
    for suite in ("extraction", "behaviour"):
        rows = [r for r in reports if r.suite == suite]
        if not rows:
            continue
        keys = sorted({k for r in rows for k in r.dimensions})
        header = ["Model", "n", "Score", *keys, "In tok", "Cached", "Out tok", "USD", "Avg ms"]
        lines += [
            f"## {suite.capitalize()}",
            "",
            "| " + " | ".join(header) + " |",
            "|" + "---|" * len(header),
        ]
        for r in sorted(rows, key=lambda r: -r.overall):
            cells = [
                f"`{r.model}`",
                str(r.n),
                _fmt(r.overall),
                *[_fmt(r.dimensions.get(k, 0.0)) for k in keys],
                str(r.totals.input_tokens),
                str(r.totals.cache_read_tokens),
                str(r.totals.output_tokens),
                f"{r.totals.cost_usd}",
                str(r.totals.avg_latency_ms),
            ]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
        unpriced = sum(r.totals.unpriced_calls for r in rows)
        if unpriced:
            lines += [
                f"> {unpriced} call(s) had no `ModelPrice` row and are **not** "
                "included in the USD column. Seed a price before comparing on cost.",
                "",
            ]
        for r in rows:
            if r.failures:
                lines += [f"### `{r.model}` — what it got wrong", ""]
                lines += [f"- {f}" for f in r.failures]
                lines.append("")
    return "\n".join(lines)


def render_json(
    reports: Sequence[ModelReport], *, generated_at: str, skipped: Sequence[str] = ()
) -> str:
    """The machine-readable twin, for diffing runs across months."""

    def encode(value):
        return str(value) if isinstance(value, Decimal) else value

    payload = {
        "generated_at": generated_at,
        "skipped": list(skipped),
        "reports": [
            {
                "model": r.model,
                "suite": r.suite,
                "n": r.n,
                "overall": r.overall,
                "dimensions": r.dimensions,
                "totals": {
                    "calls": r.totals.calls,
                    "input_tokens": r.totals.input_tokens,
                    "cache_read_tokens": r.totals.cache_read_tokens,
                    "output_tokens": r.totals.output_tokens,
                    "cost_usd": encode(r.totals.cost_usd),
                    "unpriced_calls": r.totals.unpriced_calls,
                    "avg_latency_ms": r.totals.avg_latency_ms,
                },
                "failures": list(r.failures),
            }
            for r in reports
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
