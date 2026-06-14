from datetime import date
from decimal import Decimal

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Category, PaymentMethod, SystemicExpense


class TestCockpitSystemicEditModal(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)
        self.cat = baker.make(Category, user=self.user)
        self.pm = baker.make(PaymentMethod, user=self.user, is_active=True)
        self.s = baker.make(
            SystemicExpense,
            user=self.user,
            name="Aluguel",
            category=self.cat,
            payment_method=self.pm,
            default_amount="1500",
            is_active=True,
        )
        self.entry = self.s.create_monthly_entry(date(2026, 10, 1))

    def _url(self):
        return f"/cockpit/2026/10/systemic/{self.s.pk}/edit-modal/"

    def test_get_returns_prefilled_form(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertIn("modal-edit-form", resp.content.decode())

    def test_post_updates_entry_and_rerenders_section(self):
        resp = self.client.post(
            self._url(),
            {
                "date": "2026-10-01",
                "amount": "1700.00",
                "description": "Aluguel reajustado",
                "category": self.cat.id,
                "payment_method": self.pm.id,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.amount, Decimal("1700.00"))
        self.assertEqual(self.entry.description, "Aluguel reajustado")
        self.assertIn("cockpit-systemic", resp.content.decode())
        self.assertIn("entry-saved", resp.headers.get("HX-Trigger", ""))

    def test_get_404_when_not_lancado(self):
        # A different month with no entry
        resp = self.client.get(f"/cockpit/2026/11/systemic/{self.s.pk}/edit-modal/")
        self.assertEqual(resp.status_code, 404)

    def test_cross_user_404(self):
        other = baker.make(CustomUser)
        self.client.force_login(other)
        self.assertEqual(self.client.get(self._url()).status_code, 404)

    def test_lancado_row_is_clickable(self):
        resp = self.client.get("/cockpit/2026/10/systemic/")
        html = resp.content.decode()
        self.assertIn(self._url(), html)
        self.assertIn("event.stopPropagation()", html)
