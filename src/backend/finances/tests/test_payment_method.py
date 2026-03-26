import pytest
from model_bakery import baker


@pytest.mark.django_db
class TestPaymentMethod:
    def test_create_pix(self, user):
        pm = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
        assert pm.name == "Pix"
        assert pm.type == "pix"
        assert pm.closing_day is None
        assert pm.is_active is True

    def test_create_credit_card_with_closing_day(self, user):
        pm = baker.make(
            "finances.PaymentMethod",
            user=user,
            name="Crédito Santander",
            type="credit_card",
            closing_day=30,
        )
        assert pm.closing_day == 30
        assert pm.type == "credit_card"

    def test_str_returns_name(self, user):
        pm = baker.make("finances.PaymentMethod", user=user, name="Crédito C6")
        assert str(pm) == "Crédito C6"

    def test_closing_day_null_for_non_credit(self, user):
        pm = baker.make(
            "finances.PaymentMethod",
            user=user,
            name="Dinheiro",
            type="cash",
            closing_day=None,
        )
        assert pm.closing_day is None

    def test_payment_type_choices(self):
        from finances.models.payment_method import PaymentType

        assert PaymentType.CASH == "cash"
        assert PaymentType.PIX == "pix"
        assert PaymentType.CREDIT_CARD == "credit_card"

    def test_soft_delete_via_is_active(self, user):
        pm = baker.make("finances.PaymentMethod", user=user, is_active=True)
        pm.is_active = False
        pm.save()
        pm.refresh_from_db()
        assert pm.is_active is False
