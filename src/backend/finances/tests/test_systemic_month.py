from datetime import date

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Category, Entry, PaymentMethod, SystemicExpense
from finances.models.entry import EntryType


class TestSystemicMonth(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.cat = baker.make(Category, user=self.user)
        self.pm = baker.make(PaymentMethod, user=self.user)

    def test_pairs_active_templates_with_month_entry(self):
        from finances.services.systemic_month import systemic_rows_for_month

        s1 = baker.make(SystemicExpense, user=self.user, name="Aluguel",
                        category=self.cat, payment_method=self.pm,
                        default_amount="1500", is_active=True)
        s2 = baker.make(SystemicExpense, user=self.user, name="Academia",
                        category=self.cat, payment_method=self.pm,
                        default_amount="80", is_active=True)
        baker.make(SystemicExpense, user=self.user, name="Antigo",
                   category=self.cat, payment_method=self.pm,
                   default_amount="10", is_active=False)
        entry = s1.create_monthly_entry(date(2026, 10, 1))

        rows = systemic_rows_for_month(self.user, 2026, 10)
        by_name = {r["systemic"].name: r for r in rows}
        self.assertEqual(set(by_name), {"Aluguel", "Academia"})  # inactive excluded
        self.assertEqual(by_name["Aluguel"]["entry"], entry)
        self.assertIsNone(by_name["Academia"]["entry"])

    def test_entry_from_other_month_not_paired(self):
        from finances.services.systemic_month import systemic_rows_for_month

        s1 = baker.make(SystemicExpense, user=self.user, name="Aluguel",
                        category=self.cat, payment_method=self.pm,
                        default_amount="1500", is_active=True)
        s1.create_monthly_entry(date(2026, 9, 1))
        rows = systemic_rows_for_month(self.user, 2026, 10)
        self.assertIsNone(rows[0]["entry"])
