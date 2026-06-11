from datetime import date
from decimal import Decimal

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Category, Entry, PaymentMethod, SystemicExpense
from finances.models.entry import EntryType


class TestCockpitSystemicViews(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)
        self.cat = baker.make(Category, user=self.user)
        self.pm = baker.make(PaymentMethod, user=self.user)
        self.s = baker.make(
            SystemicExpense,
            user=self.user,
            name="Aluguel",
            category=self.cat,
            payment_method=self.pm,
            default_amount="1500",
            is_active=True,
        )

    def test_lancar_creates_entry_with_default(self):
        resp = self.client.post(f"/cockpit/2026/10/systemic/{self.s.pk}/post/")
        self.assertEqual(resp.status_code, 200)
        e = Entry.objects.get(
            user=self.user, systemic_expense=self.s, billing_month=date(2026, 10, 1)
        )
        self.assertEqual(e.amount, Decimal("1500.00"))
        self.assertEqual(e.entry_type, EntryType.SYSTEMIC)

    def test_edit_amount_updates_entry(self):
        e = self.s.create_monthly_entry(date(2026, 10, 1))
        resp = self.client.post(
            f"/cockpit/2026/10/systemic/{self.s.pk}/post/", {"amount": "1600.50"}
        )
        self.assertEqual(resp.status_code, 200)
        e.refresh_from_db()
        self.assertEqual(e.amount, Decimal("1600.50"))

    def test_nao_ocorreu_deletes_entry(self):
        e = self.s.create_monthly_entry(date(2026, 10, 1))
        resp = self.client.delete(f"/cockpit/2026/10/systemic/{self.s.pk}/delete/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Entry.objects.filter(pk=e.pk).exists())
