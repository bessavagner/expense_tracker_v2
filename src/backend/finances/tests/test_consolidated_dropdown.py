from datetime import date

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Category, Entry


class TestConsolidatedDropdownToggle(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)
        cat = baker.make(Category, user=self.user, name="Alimentação")
        baker.make(
            Entry,
            user=self.user,
            category=cat,
            amount="10.00",
            date=date(2026, 1, 5),
            billing_month=date(2026, 1, 1),
        )

    def test_detail_cell_loads_only_once(self):
        """htmx must load the detail once; Alpine handles open/close afterwards."""
        resp = self.client.get("/consolidated/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # The amount cell must use the `once` modifier so re-clicks don't re-fire htmx.
        self.assertIn('hx-trigger="click once"', html)
