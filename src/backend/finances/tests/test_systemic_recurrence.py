from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.forms import SystemicEntryEditForm
from finances.models import Entry
from finances.models.entry import EntryType
from finances.services.systemic_recurrence import apply_systemic_recurrence


@pytest.fixture
def template(user):
    cat = baker.make("finances.Category", user=user)
    pm = baker.make(
        "finances.PaymentMethod", user=user, name="C6", type="credit_card", closing_day=25
    )
    return baker.make(
        "finances.SystemicExpense",
        user=user,
        name="Spotify - Amanda",
        category=cat,
        payment_method=pm,
        default_amount=Decimal("11.90"),
    )


def _launch(template, month, amount):
    return template.create_monthly_entry(month, amount=Decimal(amount))


@pytest.mark.django_db
class TestApplySystemicRecurrence:
    def test_updates_existing_and_creates_missing(self, template):
        _launch(template, date(2026, 6, 1), "11.90")  # already launched
        # Sept exists too with a stale value; July/Aug missing.
        _launch(template, date(2026, 9, 1), "11.90")

        n = apply_systemic_recurrence(
            template, Decimal("23.90"), date(2026, 6, 1), date(2026, 9, 1)
        )

        assert n == 4
        for m in (6, 7, 8, 9):
            e = Entry.objects.get(systemic_expense=template, billing_month=date(2026, m, 1))
            assert e.amount == Decimal("23.90")
            assert e.entry_type == EntryType.SYSTEMIC
            assert e.billing_month_override is True

    def test_propagates_backwards_too(self, template):
        _launch(template, date(2026, 6, 1), "11.90")

        n = apply_systemic_recurrence(
            template, Decimal("23.90"), date(2026, 4, 1), date(2026, 6, 1)
        )

        assert n == 3
        assert Entry.objects.filter(systemic_expense=template).count() == 3
        for m in (4, 5, 6):
            assert Entry.objects.get(
                systemic_expense=template, billing_month=date(2026, m, 1)
            ).amount == Decimal("23.90")

    def test_end_before_start_is_noop(self, template):
        _launch(template, date(2026, 6, 1), "11.90")
        n = apply_systemic_recurrence(
            template, Decimal("23.90"), date(2026, 6, 1), date(2026, 5, 1)
        )
        assert n == 0
        june = Entry.objects.get(systemic_expense=template, billing_month=date(2026, 6, 1))
        assert june.amount == Decimal("11.90")

    def test_does_not_touch_default_amount(self, template):
        _launch(template, date(2026, 6, 1), "11.90")
        apply_systemic_recurrence(template, Decimal("23.90"), date(2026, 6, 1), date(2026, 8, 1))
        template.refresh_from_db()
        assert template.default_amount == Decimal("11.90")

    def test_isolated_to_template(self, user, template):
        other = baker.make(
            "finances.SystemicExpense", user=user, name="Claude",
            category=template.category, payment_method=template.payment_method,
            default_amount=Decimal("100"),
        )
        oe = other.create_monthly_entry(date(2026, 7, 1), amount=Decimal("100"))

        apply_systemic_recurrence(template, Decimal("23.90"), date(2026, 6, 1), date(2026, 8, 1))

        oe.refresh_from_db()
        assert oe.amount == Decimal("100")


@pytest.mark.django_db
class TestSystemicEditFormRecurrence:
    def _data(self, template, entry, **over):
        d = {
            "name": template.name,
            "date": entry.date.isoformat(),
            "amount": "23.90",
            "category": str(entry.category_id),
            "payment_method": str(entry.payment_method_id),
        }
        d.update(over)
        return d

    def test_no_recurrence_edits_only_this_month(self, user, template):
        june = template.create_monthly_entry(date(2026, 6, 1), amount=Decimal("11.90"))
        july = template.create_monthly_entry(date(2026, 7, 1), amount=Decimal("11.90"))

        form = SystemicEntryEditForm(self._data(template, june), entry=june, user=user)
        assert form.is_valid(), form.errors
        form.save()

        june.refresh_from_db()
        july.refresh_from_db()
        assert june.amount == Decimal("23.90")
        assert july.amount == Decimal("11.90")  # untouched without recurrence

    def test_recurrence_propagates_value(self, user, template):
        june = template.create_monthly_entry(date(2026, 6, 1), amount=Decimal("11.90"))
        july = template.create_monthly_entry(date(2026, 7, 1), amount=Decimal("11.90"))

        form = SystemicEntryEditForm(
            self._data(
                template, june, is_recurring="on",
                recurrence_start="2026-06-01", recurrence_end="2026-08-01",
            ),
            entry=june, user=user,
        )
        assert form.is_valid(), form.errors
        form.save()

        july.refresh_from_db()
        assert july.amount == Decimal("23.90")
        aug = Entry.objects.get(systemic_expense=template, billing_month=date(2026, 8, 1))
        assert aug.amount == Decimal("23.90")
