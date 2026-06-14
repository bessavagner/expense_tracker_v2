from datetime import date
from decimal import Decimal

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Category, PaymentMethod, SystemicExpense


class TestCockpitSystemicCreateView(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)
        self.cat = baker.make(Category, user=self.user, name="Moradia")
        self.pm = baker.make(PaymentMethod, user=self.user, type="pix", name="Pix")

    def test_post_valid_creates_systemic_expense(self):
        resp = self.client.post(
            "/cockpit/2026/5/systemic/create/",
            {
                "name": "Internet",
                "category": str(self.cat.pk),
                "payment_method": str(self.pm.pk),
                "default_amount": "99.90",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(SystemicExpense.objects.filter(user=self.user, name="Internet").exists())

    def test_post_valid_rerenders_systemic_section(self):
        resp = self.client.post(
            "/cockpit/2026/5/systemic/create/",
            {
                "name": "Internet",
                "category": str(self.cat.pk),
                "payment_method": str(self.pm.pk),
                "default_amount": "99.90",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Internet")

    def test_section_includes_novo_form(self):
        """GET the systemic section — it must contain a novo-systemic form."""
        resp = self.client.get("/cockpit/2026/5/systemic/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "novo")

    def test_lancado_row_opens_edit_modal(self):
        """A lançado systemic row is clickable to open the edit modal (the
        inline amount field was replaced by the shared edit modal)."""
        s = baker.make(
            SystemicExpense,
            user=self.user,
            name="Aluguel",
            category=self.cat,
            payment_method=self.pm,
            default_amount=Decimal("1500"),
            is_active=True,
        )
        s.create_monthly_entry(date(2026, 5, 1))
        resp = self.client.get("/cockpit/2026/5/systemic/")
        self.assertContains(resp, f"/cockpit/2026/5/systemic/{s.pk}/edit-modal/")
        self.assertContains(resp, "cursor-pointer")
