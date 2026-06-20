from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from model_bakery import baker

from finances.models.entry import EntryType


def _e(user, cat, pm, amount, bm):
    return baker.make("finances.Entry", user=user, date=bm, amount=Decimal(amount),
                      category=cat, payment_method=pm, entry_type=EntryType.REGULAR,
                      billing_month=bm, billing_month_override=True)


@pytest.mark.django_db
def test_dry_run_does_not_write(user):
    cat = baker.make("finances.Category", user=user, name="Alimentação")
    pix = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    _e(user, cat, pix, "900", date(2026, 3, 1))
    call_command("recompute_category_averages", stdout=StringIO())
    cat.refresh_from_db()
    assert cat.quarterly_avg is None


@pytest.mark.django_db
def test_apply_populates_quarterly_avg(user, settings):
    cat = baker.make("finances.Category", user=user, name="Alimentação")
    pix = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    for bm in (date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)):
        _e(user, cat, pix, "1000", bm)
    call_command("recompute_category_averages", "--apply", "--as-of=2026-06-20",
                 stdout=StringIO())
    cat.refresh_from_db()
    assert cat.quarterly_avg == Decimal("1000.00")
