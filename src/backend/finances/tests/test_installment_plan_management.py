from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from core.models import CustomUser
from finances.models import Category, Entry, PaymentMethod
from finances.models.installment_plan import InstallmentPlan


@pytest.fixture
def plan_factory(db):
    def _make(num=3, total=Decimal("600.00"), parcela=Decimal("200.00"), start=date(2026, 6, 12),
              pm_type="pix", closing_day=None):
        user = baker.make(CustomUser)
        cat = baker.make(Category, user=user)
        pm = baker.make(PaymentMethod, user=user, type=pm_type, closing_day=closing_day)
        plan = InstallmentPlan.objects.create(
            user=user, date=start, description="Notebook", category=cat,
            payment_method=pm, total_amount=total, num_installments=num,
            installment_amount=parcela,
        )
        plan.generate_entries()
        return plan

    return _make


@pytest.mark.django_db
class TestRegenerateEntries:
    def test_regenerate_replaces_entries_with_new_values(self, plan_factory):
        plan = plan_factory(num=3, total=Decimal("600.00"), parcela=Decimal("200.00"))
        old_ids = set(plan.entries.values_list("id", flat=True))

        plan.num_installments = 4
        plan.total_amount = Decimal("800.00")
        plan.installment_amount = Decimal("200.00")
        plan.save()
        plan.regenerate_entries()

        new_ids = set(plan.entries.values_list("id", flat=True))
        assert plan.entries.count() == 4
        assert old_ids.isdisjoint(new_ids)  # entradas antigas removidas
        assert sum(e.amount for e in plan.entries.all()) == Decimal("800.00")

    def test_regenerate_is_idempotent_count(self, plan_factory):
        plan = plan_factory(num=3)
        plan.regenerate_entries()
        plan.regenerate_entries()
        assert plan.entries.count() == 3


@pytest.mark.django_db
class TestShiftMonths:
    def test_shift_forward_one_month(self, plan_factory):
        plan = plan_factory(num=3, start=date(2026, 6, 12))  # pix → jun, jul, ago
        before = list(
            plan.entries.order_by("billing_month").values_list("billing_month", flat=True)
        )
        assert before == [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]

        plan.shift_months(1)

        after = list(plan.entries.order_by("billing_month").values_list("billing_month", flat=True))
        assert after == [date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)]
        plan.refresh_from_db()
        assert plan.date == date(2026, 7, 12)

    def test_shift_backward(self, plan_factory):
        plan = plan_factory(num=2, start=date(2026, 6, 12))
        plan.shift_months(-1)
        after = list(plan.entries.order_by("billing_month").values_list("billing_month", flat=True))
        assert after == [date(2026, 5, 1), date(2026, 6, 1)]

    def test_shift_year_rollover(self, plan_factory):
        plan = plan_factory(num=2, start=date(2026, 12, 10))
        plan.shift_months(1)
        after = list(plan.entries.order_by("billing_month").values_list("billing_month", flat=True))
        assert after == [date(2027, 1, 1), date(2027, 2, 1)]


@pytest.mark.django_db
class TestDeletePlanCascade:
    def test_delete_plan_removes_all_entries(self, plan_factory):
        plan = plan_factory(num=3)
        assert Entry.objects.filter(installment_plan=plan).count() == 3
        plan.delete()
        assert Entry.objects.filter(installment_plan_id=plan.id).count() == 0
