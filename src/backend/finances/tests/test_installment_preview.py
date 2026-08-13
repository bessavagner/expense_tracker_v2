import pytest
from model_bakery import baker


@pytest.mark.django_db
class TestInstallmentPreview:
    def test_preview_credit_card_pushes_first_month(self, logged_client, household):
        pm = baker.make(
            "finances.PaymentMethod", household=household, type="credit_card", closing_day=5
        )
        response = logged_client.get(
            "/entries/installment-preview/",
            {
                "date": "2026-06-12",
                "payment_method": str(pm.id),
                "num_installments": "3",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        data = response.json()
        # closing 5, purchase 12/jun (after) → next invoice (Jul), paid Aug.
        assert data["months"] == ["08/2026", "09/2026", "10/2026"]

    def test_preview_pix_keeps_first_month_and_notes(self, logged_client, household):
        pm = baker.make("finances.PaymentMethod", household=household, type="pix")
        response = logged_client.get(
            "/entries/installment-preview/",
            {
                "date": "2026-06-12",
                "payment_method": str(pm.id),
                "num_installments": "2",
            },
            HTTP_HX_REQUEST="true",
        )
        data = response.json()
        assert data["months"] == ["06/2026", "07/2026"]
        assert data["note"]  # informa que não usa fechamento de fatura

    def test_preview_invalid_returns_empty(self, logged_client):
        response = logged_client.get(
            "/entries/installment-preview/",
            {"date": "", "payment_method": "", "num_installments": "0"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert response.json()["months"] == []

    def test_preview_rejects_another_households_payment_method(
        self, logged_client, household, other_household
    ):
        """The boundary is tenancy, not identity — and the empty answer is not
        the endpoint simply refusing everything: ours previews fine."""
        theirs = baker.make(
            "finances.PaymentMethod", household=other_household, type="credit_card", closing_day=5
        )
        ours = baker.make(
            "finances.PaymentMethod", household=household, type="credit_card", closing_day=5
        )

        def preview(pm):
            return logged_client.get(
                "/entries/installment-preview/",
                {
                    "date": "2026-06-12",
                    "payment_method": str(pm.id),
                    "num_installments": "3",
                },
                HTTP_HX_REQUEST="true",
            ).json()["months"]

        assert preview(ours) == ["08/2026", "09/2026", "10/2026"]
        assert preview(theirs) == []
