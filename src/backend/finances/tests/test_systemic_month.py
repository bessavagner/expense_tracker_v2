from datetime import date

from django.test import TestCase
from model_bakery import baker

from accounts.resolution import household_for_user
from core.models import CustomUser
from finances.models import Category, PaymentMethod, SystemicExpense


class TestSystemicMonth(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.other_user = baker.make(CustomUser)
        self.household = household_for_user(self.user)
        self.other_household = household_for_user(self.other_user)
        self.cat = baker.make(Category, user=self.user)
        self.pm = baker.make(PaymentMethod, user=self.user)

    def test_pairs_active_templates_with_month_entry(self):
        from finances.services.systemic_month import systemic_rows_for_month

        s1 = baker.make(
            SystemicExpense,
            user=self.user,
            name="Aluguel",
            category=self.cat,
            payment_method=self.pm,
            default_amount="1500",
            is_active=True,
        )
        baker.make(
            SystemicExpense,
            user=self.user,
            name="Academia",
            category=self.cat,
            payment_method=self.pm,
            default_amount="80",
            is_active=True,
        )
        baker.make(
            SystemicExpense,
            user=self.user,
            name="Antigo",
            category=self.cat,
            payment_method=self.pm,
            default_amount="10",
            is_active=False,
        )
        entry = s1.create_monthly_entry(date(2026, 10, 1))

        rows = systemic_rows_for_month(self.household, 2026, 10)
        by_name = {r["systemic"].name: r for r in rows}
        self.assertEqual(set(by_name), {"Aluguel", "Academia"})  # inactive excluded
        self.assertEqual(by_name["Aluguel"]["entry"], entry)
        self.assertIsNone(by_name["Academia"]["entry"])

    def test_entry_from_other_month_not_paired(self):
        from finances.services.systemic_month import systemic_rows_for_month

        s1 = baker.make(
            SystemicExpense,
            user=self.user,
            name="Aluguel",
            category=self.cat,
            payment_method=self.pm,
            default_amount="1500",
            is_active=True,
        )
        s1.create_monthly_entry(date(2026, 9, 1))
        rows = systemic_rows_for_month(self.household, 2026, 10)
        self.assertIsNone(rows[0]["entry"])

    def test_systemic_rows_exclude_other_households(self):
        """The neighbour's template must not reach this household's cockpit."""
        from finances.services.systemic_month import systemic_rows_for_month

        other_cat = baker.make(Category, user=self.other_user)
        other_pm = baker.make(PaymentMethod, user=self.other_user)
        baker.make(
            SystemicExpense,
            user=self.other_user,
            name="Aluguel do vizinho",
            category=other_cat,
            payment_method=other_pm,
            default_amount="9999",
            is_active=True,
        )

        self.assertEqual(systemic_rows_for_month(self.household, 2026, 10), [])
        self.assertEqual(len(systemic_rows_for_month(self.other_household, 2026, 10)), 1)

    def test_systemic_rows_of_no_household_are_empty(self):
        """Fail closed: an unresolved tenant is never 'every template'."""
        from finances.services.systemic_month import systemic_rows_for_month

        baker.make(
            SystemicExpense,
            user=self.user,
            name="Aluguel",
            category=self.cat,
            payment_method=self.pm,
            default_amount="1500",
            is_active=True,
        )

        self.assertEqual(systemic_rows_for_month(None, 2026, 10), [])
