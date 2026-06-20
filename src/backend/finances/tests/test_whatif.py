from datetime import date
from decimal import Decimal

from finances.services.whatif import (
    HypotheticalItem,
    HypoType,
    add_months,
    expand_hypotheticals,
)

SPAN = [date(2026, m, 1) for m in range(1, 13)]  # all of 2026


def _item(**kw):
    base = {"id": "x", "type": HypoType.EXPENSE_ONEOFF, "label": "t",
            "amount": Decimal("0"), "month": date(2026, 3, 1)}
    base.update(kw)
    return HypotheticalItem(**base)


def test_add_months_wraps_year():
    assert add_months(date(2026, 11, 1), 3) == date(2027, 2, 1)


def test_expense_oneoff():
    overlay, ignored = expand_hypotheticals(
        [_item(type=HypoType.EXPENSE_ONEOFF, amount=Decimal("300"), month=date(2026, 3, 1))],
        SPAN,
    )
    assert overlay == {(date(2026, 3, 1), "regular"): Decimal("300.00")}
    assert ignored == 0


def test_expense_recurring_inclusive_range():
    overlay, _ = expand_hypotheticals(
        [_item(type=HypoType.EXPENSE_RECURRING, amount=Decimal("100"),
               month=date(2026, 3, 1), end_month=date(2026, 5, 1))],
        SPAN,
    )
    assert overlay == {
        (date(2026, 3, 1), "regular"): Decimal("100.00"),
        (date(2026, 4, 1), "regular"): Decimal("100.00"),
        (date(2026, 5, 1), "regular"): Decimal("100.00"),
    }


def test_income_oneoff():
    overlay, _ = expand_hypotheticals(
        [_item(type=HypoType.INCOME, amount=Decimal("2000"), month=date(2026, 6, 1))], SPAN
    )
    assert overlay == {(date(2026, 6, 1), "income"): Decimal("2000.00")}


def test_installment_spreads_n_months():
    overlay, _ = expand_hypotheticals(
        [_item(type=HypoType.INSTALLMENT, amount=Decimal("400"),
               month=date(2026, 1, 1), n_installments=3)],
        SPAN,
    )
    assert overlay == {
        (date(2026, 1, 1), "installment"): Decimal("400.00"),
        (date(2026, 2, 1), "installment"): Decimal("400.00"),
        (date(2026, 3, 1), "installment"): Decimal("400.00"),
    }


def test_loan_income_now_parcelas_from_next_month():
    overlay, _ = expand_hypotheticals(
        [_item(type=HypoType.LOAN, amount=Decimal("20000"), month=date(2026, 6, 1),
               n_installments=2, installment_amount=Decimal("1900"))],
        SPAN,
    )
    assert overlay == {
        (date(2026, 6, 1), "income"): Decimal("20000.00"),
        (date(2026, 7, 1), "installment"): Decimal("1900.00"),
        (date(2026, 8, 1), "installment"): Decimal("1900.00"),
    }


def test_deltas_outside_span_are_ignored_and_counted():
    overlay, ignored = expand_hypotheticals(
        [_item(type=HypoType.EXPENSE_ONEOFF, amount=Decimal("50"), month=date(2030, 1, 1))],
        SPAN,
    )
    assert overlay == {}
    assert ignored == 1


def test_same_month_kind_amounts_accumulate():
    overlay, _ = expand_hypotheticals(
        [
            _item(type=HypoType.EXPENSE_ONEOFF, amount=Decimal("100"), month=date(2026, 3, 1)),
            _item(type=HypoType.EXPENSE_ONEOFF, amount=Decimal("25"), month=date(2026, 3, 1)),
        ],
        SPAN,
    )
    assert overlay == {(date(2026, 3, 1), "regular"): Decimal("125.00")}
