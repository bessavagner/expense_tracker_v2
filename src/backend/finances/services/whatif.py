"""What-if projection primitives.

Pure, deterministic. Shared by the projection screen (session) and the planner
agent tool. NO import of pydantic_ai here — only pydantic — so finances stays
decoupled from the agent framework.
"""

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from pydantic import BaseModel

_CENTS = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)


def add_months(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) + n
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


class HypoType(StrEnum):
    EXPENSE_ONEOFF = "expense_oneoff"
    EXPENSE_RECURRING = "expense_recurring"
    INCOME = "income"
    INSTALLMENT = "installment"
    LOAN = "loan"


class HypotheticalItem(BaseModel):
    id: str
    type: HypoType
    label: str = ""
    amount: Decimal
    month: date
    end_month: date | None = None
    n_installments: int | None = None
    installment_amount: Decimal | None = None


def _item_deltas(item: HypotheticalItem):
    """Yield (billing_month, kind, amount) tuples for one hypothetical."""
    m = item.month.replace(day=1)
    if item.type == HypoType.EXPENSE_ONEOFF:
        yield (m, "regular", item.amount)
    elif item.type == HypoType.EXPENSE_RECURRING:
        end = (item.end_month or item.month).replace(day=1)
        cur = m
        while cur <= end:
            yield (cur, "regular", item.amount)
            cur = add_months(cur, 1)
    elif item.type == HypoType.INCOME:
        if item.end_month:
            end = item.end_month.replace(day=1)
            cur = m
            while cur <= end:
                yield (cur, "income", item.amount)
                cur = add_months(cur, 1)
        else:
            yield (m, "income", item.amount)
    elif item.type == HypoType.INSTALLMENT:
        for i in range(item.n_installments or 0):
            yield (add_months(m, i), "installment", item.amount)
    elif item.type == HypoType.LOAN:
        yield (m, "income", item.amount)
        parcela = item.installment_amount or Decimal("0")
        for i in range(item.n_installments or 0):
            yield (add_months(m, i + 1), "installment", parcela)


def expand_hypotheticals(
    items: list[HypotheticalItem], span_months: list[date]
) -> tuple[dict[tuple[date, str], Decimal], int]:
    span = set(span_months)
    deltas: dict[tuple[date, str], Decimal] = defaultdict(lambda: Decimal("0"))
    ignored = 0
    for item in items:
        for m, kind, amount in _item_deltas(item):
            if m in span:
                deltas[(m, kind)] += Decimal(amount)
            else:
                ignored += 1
    return {k: _q(v) for k, v in deltas.items()}, ignored
