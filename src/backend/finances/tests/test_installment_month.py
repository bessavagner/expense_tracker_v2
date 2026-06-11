from datetime import date
from decimal import Decimal

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Category, PaymentMethod
from finances.models.installment_plan import InstallmentPlan


class TestInstallmentRowsForMonth(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.other_user = baker.make(CustomUser)
        self.cat = baker.make(Category, user=self.user)
        self.pm = baker.make(PaymentMethod, user=self.user, type="pix")

    def _make_plan(self, description, num=6, amount=Decimal("100.00"), user=None):
        user = user or self.user
        cat = baker.make(Category, user=user)
        pm = baker.make(PaymentMethod, user=user, type="pix")
        plan = InstallmentPlan.objects.create(
            user=user,
            date=date(2026, 1, 1),
            description=description,
            category=cat,
            payment_method=pm,
            total_amount=amount * num,
            num_installments=num,
            installment_amount=amount,
        )
        plan.generate_entries()
        return plan

    def test_mid_plan_shows_correct_parcela_num_and_remaining(self):
        """A 6-instalment plan started Jan-2026: at month 3 we should see parcela_num=3."""
        from finances.services.installment_month import installment_rows_for_month

        plan = self._make_plan("Notebook", num=6, amount=Decimal("100.00"))
        # Plan generates entries for Jan, Feb, Mar, Apr, May, Jun 2026
        rows = installment_rows_for_month(self.user, 2026, 3)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["plan"], plan)
        self.assertEqual(row["parcela_num"], 3)
        self.assertEqual(row["num_installments"], 6)
        self.assertEqual(row["installment_amount"], Decimal("100.00"))
        # Remaining after 3 instalments paid (months 1,2,3): total 600 - 300 = 300
        self.assertEqual(row["remaining"], Decimal("300.00"))

    def test_plan_with_no_entry_in_month_excluded(self):
        """A plan that has no entry in the queried month should not appear."""
        from finances.services.installment_month import installment_rows_for_month

        self._make_plan("Notebook", num=3, amount=Decimal("100.00"))
        # Plan covers Jan, Feb, Mar 2026 — querying April should yield nothing
        rows = installment_rows_for_month(self.user, 2026, 4)
        self.assertEqual(rows, [])

    def test_other_user_plans_excluded(self):
        """Plans belonging to another user must not appear."""
        from finances.services.installment_month import installment_rows_for_month

        self._make_plan("Other notebook", num=6, amount=Decimal("50.00"), user=self.other_user)
        rows = installment_rows_for_month(self.user, 2026, 3)
        self.assertEqual(rows, [])

    def test_first_month_parcela_num_is_1(self):
        from finances.services.installment_month import installment_rows_for_month

        self._make_plan("TV", num=4, amount=Decimal("250.00"))
        rows = installment_rows_for_month(self.user, 2026, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["parcela_num"], 1)
        self.assertEqual(rows[0]["remaining"], Decimal("750.00"))

    def test_last_month_remaining_is_zero(self):
        from finances.services.installment_month import installment_rows_for_month

        self._make_plan("TV", num=3, amount=Decimal("100.00"))
        rows = installment_rows_for_month(self.user, 2026, 3)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["parcela_num"], 3)
        self.assertEqual(rows[0]["remaining"], Decimal("0.00"))

    def test_multiple_plans_ordered_by_description(self):
        from finances.services.installment_month import installment_rows_for_month

        self._make_plan("Zebra", num=6, amount=Decimal("50.00"))
        self._make_plan("Alpha", num=6, amount=Decimal("80.00"))
        rows = installment_rows_for_month(self.user, 2026, 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["plan"].description, "Alpha")
        self.assertEqual(rows[1]["plan"].description, "Zebra")
