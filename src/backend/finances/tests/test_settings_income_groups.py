from datetime import date
from decimal import Decimal

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Income


class TestIncomeGrouping(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)

    def _make(self, name, amount, month, recurring=False):
        return baker.make(
            Income, user=self.user, name=name, amount=amount, month=month,
            is_recurring=recurring,
        )

    def test_groups_recurring_income_into_one_row(self):
        from finances.views.settings import income_groups

        self._make("Salário", "8000.00", date(2026, 1, 1), recurring=True)
        self._make("Salário", "8000.00", date(2026, 2, 1), recurring=True)
        self._make("Salário", "8000.00", date(2026, 3, 1), recurring=True)
        self._make("Freela", "500.00", date(2026, 2, 1))

        groups = {g["name"]: g for g in income_groups(self.user)}
        self.assertEqual(set(groups), {"Salário", "Freela"})
        sal = groups["Salário"]
        self.assertEqual(sal["count"], 3)
        self.assertEqual(sal["min_month"], date(2026, 1, 1))
        self.assertEqual(sal["max_month"], date(2026, 3, 1))
        self.assertEqual(sal["amount"], Decimal("8000.00"))
        self.assertTrue(sal["is_recurring"])

    def test_amount_is_none_when_months_differ(self):
        from finances.views.settings import income_groups

        self._make("Bônus", "1000.00", date(2026, 1, 1))
        self._make("Bônus", "1500.00", date(2026, 6, 1))
        g = income_groups(self.user)[0]
        self.assertIsNone(g["amount"])  # "vários"
        self.assertEqual(g["count"], 2)

    def test_tab_renders_grouped_not_every_month(self):
        for m in range(1, 13):
            self._make("Salário", "8000.00", date(2026, m, 1), recurring=True)
        resp = self.client.get("/settings/income/")
        body = resp.content.decode()
        # One grouped row (one delete control), not twelve rows; shows the count.
        self.assertEqual(body.count("income/group-delete"), 1)
        self.assertIn("12", body)  # "12 meses"


class TestIncomeGroupDelete(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)

    def test_deletes_all_rows_of_a_name(self):
        for m in range(1, 13):
            baker.make(Income, user=self.user, name="Salário", amount="8000",
                       month=date(2026, m, 1))
        baker.make(Income, user=self.user, name="Freela", amount="500", month=date(2026, 1, 1))
        resp = self.client.post("/settings/income/group-delete/", {"name": "Salário"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Income.objects.filter(user=self.user, name="Salário").count(), 0)
        self.assertEqual(Income.objects.filter(user=self.user, name="Freela").count(), 1)

    def test_does_not_touch_other_users(self):
        other = baker.make(CustomUser)
        baker.make(Income, user=other, name="Salário", amount="8000", month=date(2026, 1, 1))
        self.client.post("/settings/income/group-delete/", {"name": "Salário"})
        self.assertEqual(Income.objects.filter(user=other, name="Salário").count(), 1)
