from datetime import date
from decimal import Decimal

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Category, Entry, PaymentMethod
from finances.models.entry import EntryType
from finances.models.installment_plan import InstallmentPlan


class TestCockpitParcelamentoEditModal(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)
        self.cat = baker.make(Category, user=self.user)
        self.pm = baker.make(PaymentMethod, user=self.user, type="pix", is_active=True)
        self.plan = InstallmentPlan.objects.create(
            user=self.user,
            date=date(2026, 1, 1),
            description="Notebook",
            category=self.cat,
            payment_method=self.pm,
            total_amount=Decimal("600.00"),
            num_installments=6,
            installment_amount=Decimal("100.00"),
        )
        self.plan.generate_entries()
        self.entry = Entry.objects.get(
            installment_plan=self.plan,
            entry_type=EntryType.INSTALLMENT,
            billing_month=date(2026, 3, 1),
        )

    def _url(self):
        return f"/cockpit/2026/3/parcelamento/{self.entry.id}/edit-modal/"

    def test_get_returns_prefilled_form(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertIn("modal-edit-form", resp.content.decode())

    def test_post_updates_entry_and_rerenders_section(self):
        resp = self.client.post(
            self._url(),
            {
                "date": "2026-01-01",
                "amount": "150.00",
                "description": "Notebook (ajuste parcela 3)",
                "category": self.cat.id,
                "payment_method": self.pm.id,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.amount, Decimal("150.00"))
        self.assertIn("cockpit-parcelamentos", resp.content.decode())
        self.assertIn("entry-saved", resp.headers.get("HX-Trigger", ""))

    def test_cross_user_404(self):
        other = baker.make(CustomUser)
        self.client.force_login(other)
        self.assertEqual(self.client.get(self._url()).status_code, 404)

    def test_row_is_clickable(self):
        resp = self.client.get("/cockpit/2026/3/parcelamentos/")
        self.assertContains(resp, self._url())
        self.assertContains(resp, "cursor-pointer")
