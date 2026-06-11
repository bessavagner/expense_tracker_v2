# src/backend/finances/tests/test_cockpit_income_views.py
from datetime import date

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Income


class TestCockpitIncomeViews(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)

    def test_create_income_for_month_renders_section(self):
        resp = self.client.post(
            "/cockpit/2026/10/income/create/",
            {"name": "Salário", "amount": "5000.00", "month": "2026-10-01"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Salário", resp.content.decode())
        self.assertEqual(Income.objects.filter(user=self.user, month=date(2026, 10, 1)).count(), 1)

    def test_section_lists_only_selected_month(self):
        baker.make(Income, user=self.user, name="Out", amount="100", month=date(2026, 10, 1))
        baker.make(Income, user=self.user, name="Nov", amount="200", month=date(2026, 11, 1))
        resp = self.client.get("/cockpit/2026/10/income/")
        body = resp.content.decode()
        self.assertIn("Out", body)
        self.assertNotIn("Nov", body)

    def test_delete_income_removes_row(self):
        inc = baker.make(Income, user=self.user, name="X", amount="100", month=date(2026, 10, 1))
        resp = self.client.delete(f"/cockpit/2026/10/income/{inc.pk}/delete/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Income.objects.filter(pk=inc.pk).exists())

    def test_user_cannot_touch_another_users_income(self):
        other = baker.make(CustomUser)
        inc = baker.make(Income, user=other, name="X", amount="100", month=date(2026, 10, 1))
        resp = self.client.delete(f"/cockpit/2026/10/income/{inc.pk}/delete/")
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Income.objects.filter(pk=inc.pk).exists())
