from datetime import date

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import PaymentMethod
from finances.models.payment_method import PaymentType
from finances.models.payment_method_closing_day import PaymentMethodClosingDay


class TestCockpitVencimentos(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)
        self.pm = baker.make(
            PaymentMethod,
            user=self.user,
            name="Nubank",
            type=PaymentType.CREDIT_CARD,
            closing_day=10,
            is_active=True,
        )

    def test_section_lists_only_active_credit_cards(self):
        baker.make(PaymentMethod, user=self.user, name="Pix", type=PaymentType.PIX, is_active=True)
        resp = self.client.get("/cockpit/2026/10/vencimentos/")
        body = resp.content.decode()
        self.assertIn("Nubank", body)
        self.assertNotIn("Pix", body)

    def test_set_override_creates_row(self):
        resp = self.client.post(
            f"/cockpit/2026/10/vencimentos/{self.pm.pk}/", {"closing_day": "12"}
        )
        self.assertEqual(resp.status_code, 200)
        ov = PaymentMethodClosingDay.objects.get(
            payment_method=self.pm, month=date(2026, 10, 1)
        )
        self.assertEqual(ov.closing_day, 12)

    def test_update_override(self):
        baker.make(
            PaymentMethodClosingDay,
            payment_method=self.pm,
            month=date(2026, 10, 1),
            closing_day=12,
        )
        self.client.post(
            f"/cockpit/2026/10/vencimentos/{self.pm.pk}/", {"closing_day": "15"}
        )
        ov = PaymentMethodClosingDay.objects.get(
            payment_method=self.pm, month=date(2026, 10, 1)
        )
        self.assertEqual(ov.closing_day, 15)

    def test_clear_override_reverts_to_default(self):
        baker.make(
            PaymentMethodClosingDay,
            payment_method=self.pm,
            month=date(2026, 10, 1),
            closing_day=12,
        )
        self.client.post(
            f"/cockpit/2026/10/vencimentos/{self.pm.pk}/", {"closing_day": ""}
        )
        self.assertFalse(
            PaymentMethodClosingDay.objects.filter(
                payment_method=self.pm, month=date(2026, 10, 1)
            ).exists()
        )
