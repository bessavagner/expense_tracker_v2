from datetime import date
from decimal import Decimal

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Category, PaymentMethod
from finances.models.installment_plan import InstallmentPlan


class TestCockpitParcelamentosSectionView(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)
        self.cat = baker.make(Category, user=self.user)
        self.pm = baker.make(PaymentMethod, user=self.user, type="pix")

    def _make_plan(self, description, num=6, amount=Decimal("100.00")):
        plan = InstallmentPlan.objects.create(
            user=self.user,
            date=date(2026, 1, 1),
            description=description,
            category=self.cat,
            payment_method=self.pm,
            total_amount=amount * num,
            num_installments=num,
            installment_amount=amount,
        )
        plan.generate_entries()
        return plan

    def test_section_returns_200(self):
        resp = self.client.get("/cockpit/2026/3/parcelamentos/")
        self.assertEqual(resp.status_code, 200)

    def test_section_shows_plan_in_month(self):
        plan = self._make_plan("Notebook", num=6, amount=Decimal("200.00"))
        resp = self.client.get("/cockpit/2026/3/parcelamentos/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, plan.description)
        self.assertContains(resp, "3/6")

    def test_section_empty_state(self):
        resp = self.client.get("/cockpit/2026/3/parcelamentos/")
        self.assertContains(resp, "Nenhum parcelamento")

    def test_plan_not_in_month_excluded(self):
        """A plan that ends before the queried month should not appear."""
        self._make_plan("TV", num=2, amount=Decimal("100.00"))
        # Plan covers Jan, Feb 2026 — April should show empty
        resp = self.client.get("/cockpit/2026/4/parcelamentos/")
        self.assertContains(resp, "Nenhum parcelamento")
        self.assertNotContains(resp, "TV")

    def test_other_user_plan_not_shown(self):
        other = baker.make(CustomUser)
        other_cat = baker.make(Category, user=other)
        other_pm = baker.make(PaymentMethod, user=other, type="pix")
        plan = InstallmentPlan.objects.create(
            user=other,
            date=date(2026, 1, 1),
            description="OtherNotebook",
            category=other_cat,
            payment_method=other_pm,
            total_amount=Decimal("600.00"),
            num_installments=6,
            installment_amount=Decimal("100.00"),
        )
        plan.generate_entries()
        resp = self.client.get("/cockpit/2026/3/parcelamentos/")
        self.assertNotContains(resp, "OtherNotebook")
