# src/backend/finances/tests/test_cockpit_income_views.py
from datetime import date

from django.test import TestCase
from model_bakery import baker

from accounts.resolution import household_for_user
from conftest import complete_onboarding
from core.models import CustomUser
from finances.models import Income


class TestCockpitIncomeViews(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        # Resolved for its side effect: it mints the Membership the middleware
        # reads. Without one `request.household` is None, and since phase 4
        # made the column NOT NULL that is an IntegrityError on the first
        # write rather than a quietly empty read. Onboarded, too — from E11 a
        # household that has not finished the guided setup is redirected out
        # of every GET.
        self.household = complete_onboarding(household_for_user(self.user))
        self.client.force_login(self.user)

    def test_create_income_for_month_renders_section(self):
        resp = self.client.post(
            "/cockpit/2026/10/income/create/",
            {"name": "Salário", "amount": "5000.00", "month": "2026-10-01"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Salário", resp.content.decode())
        self.assertEqual(
            Income.objects.for_household(household_for_user(self.user))
            .filter(month=date(2026, 10, 1))
            .count(),
            1,
        )

    def test_section_lists_only_selected_month(self):
        baker.make(
            Income,
            household=household_for_user(self.user),
            name="Out",
            amount="100",
            month=date(2026, 10, 1),
        )
        baker.make(
            Income,
            household=household_for_user(self.user),
            name="Nov",
            amount="200",
            month=date(2026, 11, 1),
        )
        resp = self.client.get("/cockpit/2026/10/income/")
        body = resp.content.decode()
        # Anchor on the rendered cell, not the whole document: a bare
        # `assertNotIn("Nov", body)` also reads the CSRF token, and a random
        # token containing "Nov" fails the test for no reason (seen in CI).
        self.assertIn("<td>Out</td>", body)
        self.assertNotIn("<td>Nov</td>", body)

    def test_delete_income_removes_row(self):
        inc = baker.make(
            Income,
            household=household_for_user(self.user),
            name="X",
            amount="100",
            month=date(2026, 10, 1),
        )
        resp = self.client.delete(f"/cockpit/2026/10/income/{inc.pk}/delete/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Income.objects.filter(pk=inc.pk).exists())

    def test_cannot_touch_another_households_income(self):
        """The boundary is tenancy, not identity."""
        other = baker.make(CustomUser)
        inc = baker.make(
            Income,
            household=household_for_user(other),
            name="X",
            amount="100",
            month=date(2026, 10, 1),
        )
        resp = self.client.delete(f"/cockpit/2026/10/income/{inc.pk}/delete/")
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Income.objects.filter(pk=inc.pk).exists())
