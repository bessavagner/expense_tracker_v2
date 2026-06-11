# src/backend/finances/tests/test_cockpit_income.py
from datetime import date

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Income


class TestCockpitIncomeForm(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)

    def test_repeat_until_december_creates_one_row_per_month(self):
        from finances.forms import CockpitIncomeForm

        form = CockpitIncomeForm(
            data={"name": "Salário", "amount": "5000.00", "month": "2026-10-01",
                  "repeat_until_december": True}
        )
        self.assertTrue(form.is_valid(), form.errors)
        created = form.save_for_user(self.user)
        # Oct, Nov, Dec => 3 rows
        self.assertEqual(len(created), 3)
        months = sorted(i.month for i in created)
        self.assertEqual(months, [date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1)])
        self.assertTrue(all(i.amount.quantize(__import__("decimal").Decimal("0.01"))
                            == __import__("decimal").Decimal("5000.00") for i in created))
        self.assertTrue(all(i.user_id == self.user.id for i in created))

    def test_without_repeat_creates_single_row(self):
        from finances.forms import CockpitIncomeForm

        form = CockpitIncomeForm(
            data={"name": "Freela", "amount": "800.00", "month": "2026-10-01",
                  "repeat_until_december": False}
        )
        self.assertTrue(form.is_valid(), form.errors)
        created = form.save_for_user(self.user)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].month, date(2026, 10, 1))
        self.assertEqual(Income.objects.filter(user=self.user).count(), 1)
