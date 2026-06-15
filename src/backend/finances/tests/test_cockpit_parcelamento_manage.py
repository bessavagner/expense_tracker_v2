from datetime import date
from decimal import Decimal

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Category, Entry, PaymentMethod
from finances.models.entry import EntryType
from finances.models.installment_plan import InstallmentPlan


class TestCockpitParcelamentoManage(TestCase):
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
        return f"/cockpit/2026/3/parcelamento/{self.entry.id}/manage/"

    def test_get_returns_plan_and_parcela_tabs(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Plano inteiro", body)
        self.assertIn("Esta parcela", body)

    def test_edit_plan_regenerates_entries(self):
        resp = self.client.post(
            self._url(),
            {
                "action": "edit_plan",
                "date": "2026-01-01",
                "description": "Notebook PRO",
                "category": self.cat.id,
                "payment_method": self.pm.id,
                "total_amount": "800.00",
                "num_installments": "4",
                "installment_amount": "200.00",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.description, "Notebook PRO")
        self.assertEqual(
            Entry.objects.filter(installment_plan=self.plan).count(), 4
        )
        self.assertIn("entry-saved", resp.headers.get("HX-Trigger", ""))

    def test_shift_months_forward(self):
        resp = self.client.post(self._url(), {"action": "shift", "months": "1"})
        self.assertEqual(resp.status_code, 200)
        months = list(
            Entry.objects.filter(installment_plan=self.plan)
            .order_by("billing_month")
            .values_list("billing_month", flat=True)
        )
        # Original: Jan..Jun 2026 → after +1: Feb..Jul 2026
        self.assertEqual(months[0], date(2026, 2, 1))
        self.assertIn("entry-saved", resp.headers.get("HX-Trigger", ""))

    def test_delete_plan_removes_everything(self):
        resp = self.client.post(self._url(), {"action": "delete"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(InstallmentPlan.objects.filter(id=self.plan.id).exists())
        self.assertEqual(
            Entry.objects.filter(installment_plan_id=self.plan.id).count(), 0
        )
        self.assertIn("entry-saved", resp.headers.get("HX-Trigger", ""))

    def test_cross_user_404(self):
        other = baker.make(CustomUser)
        self.client.force_login(other)
        self.assertEqual(self.client.get(self._url()).status_code, 404)

    def test_row_points_to_manage_modal(self):
        resp = self.client.get("/cockpit/2026/3/parcelamentos/")
        self.assertContains(resp, self._url())
