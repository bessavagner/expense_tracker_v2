import io
from datetime import date as dt

import pytest
from django.test import Client
from model_bakery import baker

from finances.models import Entry, InstallmentPlan

_SIMPLE_CSV = (
    b'data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n01/03/2026,"R$ 42,00",Test,Food,Pix\n'
)

_MAPPING_REGULAR = {
    "date": "0",
    "amount": "1",
    "description": "2",
    "category": "3",
    "payment_method": "4",
}


@pytest.mark.django_db
class TestImportUploadView:
    def test_upload_page_renders(self, logged_client):
        response = logged_client.get("/import/")
        assert response.status_code == 200
        assert "importer/import_page.html" in [t.name for t in response.templates]

    def test_upload_csv_file(self, logged_client):
        csv_file = io.BytesIO(_SIMPLE_CSV)
        csv_file.name = "test.csv"
        response = logged_client.post(
            "/import/",
            data={"file": csv_file, "import_type": "regular"},
        )
        assert response.status_code == 302  # redirects to mapping step

    def test_upload_no_file_shows_error(self, logged_client):
        response = logged_client.post(
            "/import/",
            data={"import_type": "regular"},
        )
        assert response.status_code == 200  # re-renders form with error

    def test_unauthenticated_redirects(self):
        client = Client()
        response = client.get("/import/")
        assert response.status_code == 302


@pytest.mark.django_db
class TestImportMappingView:
    def _upload_first(self, logged_client):
        csv_file = io.BytesIO(_SIMPLE_CSV)
        csv_file.name = "test.csv"
        logged_client.post("/import/", data={"file": csv_file, "import_type": "regular"})

    def test_mapping_page_renders(self, logged_client):
        self._upload_first(logged_client)
        response = logged_client.get("/import/map/")
        assert response.status_code == 200
        assert "mapping" in response.context

    def test_mapping_auto_detects_columns(self, logged_client):
        self._upload_first(logged_client)
        response = logged_client.get("/import/map/")
        mapping = response.context["mapping"]
        assert mapping["date"] == 0
        assert mapping["amount"] == 1
        assert mapping["description"] == 2

    def test_confirm_mapping_redirects_to_preview(self, logged_client):
        self._upload_first(logged_client)
        response = logged_client.post("/import/map/", data=_MAPPING_REGULAR)
        assert response.status_code == 302  # redirects to preview

    def test_no_session_redirects_to_upload(self, logged_client):
        response = logged_client.get("/import/map/")
        assert response.status_code == 302


@pytest.mark.django_db
class TestImportPreviewView:
    def _setup_session(self, logged_client, user):
        """Upload and map a CSV to get to preview step."""
        baker.make("finances.Category", user=user, name="Álcool")
        baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
        csv_content = (
            b"data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n"
            b'01/03/2026,"R$ 42,00",Heineken,\xc3\x81lcool,Pix\n'
            b'02/03/2026,"R$ 14,00",Disk Bebida,NewCat,Pix\n'
        )
        csv_file = io.BytesIO(csv_content)
        csv_file.name = "test.csv"
        logged_client.post("/import/", data={"file": csv_file, "import_type": "regular"})
        logged_client.post("/import/map/", data=_MAPPING_REGULAR)

    def test_preview_page_renders(self, logged_client, user):
        self._setup_session(logged_client, user)
        response = logged_client.get("/import/preview/")
        assert response.status_code == 200
        assert "rows" in response.context

    def test_preview_shows_unmatched_categories(self, logged_client, user):
        self._setup_session(logged_client, user)
        response = logged_client.get("/import/preview/")
        assert "NewCat" in response.context["unmatched_categories"]

    def test_no_session_redirects(self, logged_client):
        response = logged_client.get("/import/preview/")
        assert response.status_code == 302


@pytest.mark.django_db
class TestImportExecuteView:
    def _setup_to_preview(self, logged_client, user):
        baker.make("finances.Category", user=user, name="Álcool")
        baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
        csv_content = (
            b"data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n"
            b'01/03/2026,"R$ 42,00",Heineken,\xc3\x81lcool,Pix\n'
            b'05/03/2026,"R$ 14,00",Disk Bebida,\xc3\x81lcool,Pix\n'
        )
        csv_file = io.BytesIO(csv_content)
        csv_file.name = "test.csv"
        logged_client.post("/import/", data={"file": csv_file, "import_type": "regular"})
        logged_client.post("/import/map/", data=_MAPPING_REGULAR)

    def test_execute_creates_entries(self, logged_client, user):
        self._setup_to_preview(logged_client, user)
        response = logged_client.post("/import/execute/")
        assert response.status_code == 200
        assert Entry.objects.filter(user=user).count() == 2

    def test_execute_entries_have_correct_billing_month(self, logged_client, user):
        self._setup_to_preview(logged_client, user)
        logged_client.post("/import/execute/")
        entry = Entry.objects.filter(user=user, description="Heineken").first()
        assert entry is not None
        assert entry.billing_month == dt(2026, 3, 1)

    def test_execute_clears_session(self, logged_client, user):
        self._setup_to_preview(logged_client, user)
        logged_client.post("/import/execute/")
        assert "import_data" not in logged_client.session

    def test_execute_installments(self, logged_client, user):
        baker.make("finances.Category", user=user, name="Roupa")
        baker.make(
            "finances.PaymentMethod",
            user=user,
            name="Crédito C6",
            type="credit_card",
            closing_day=25,
        )
        csv_content = (
            b"data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma,parcelas,valor_parcela\n"
            b'01/11/2025,"R$ 193,19",Mercado Livre - Camisetas,'
            b'Roupa,Cr\xc3\xa9dito C6,2,"R$ 96,60"\n'
        )
        csv_file = io.BytesIO(csv_content)
        csv_file.name = "test.csv"
        logged_client.post("/import/", data={"file": csv_file, "import_type": "installment"})
        logged_client.post(
            "/import/map/",
            data={
                "date": "0",
                "total_amount": "1",
                "description": "2",
                "category": "3",
                "payment_method": "4",
                "num_installments": "5",
                "installment_amount": "6",
            },
        )
        response = logged_client.post("/import/execute/")
        assert response.status_code == 200
        assert InstallmentPlan.objects.filter(user=user).count() == 1
        assert Entry.objects.filter(user=user, entry_type="installment").count() == 2

    def test_execute_skips_duplicates_marked_for_skip(self, logged_client, user):
        cat = baker.make("finances.Category", user=user, name="Álcool")
        pm = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
        # Pre-existing entry
        baker.make(
            "finances.Entry",
            user=user,
            date=dt(2026, 3, 1),
            amount="42.00",
            description="Heineken",
            category=cat,
            payment_method=pm,
            billing_month=dt(2026, 3, 1),
            billing_month_override=True,
        )
        csv_content = (
            b"data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n"
            b'01/03/2026,"R$ 42,00",Heineken,\xc3\x81lcool,Pix\n'
        )
        csv_file = io.BytesIO(csv_content)
        csv_file.name = "test.csv"
        logged_client.post("/import/", data={"file": csv_file, "import_type": "regular"})
        logged_client.post("/import/map/", data=_MAPPING_REGULAR)
        # Mark duplicate for skip
        session = logged_client.session
        import_data = session["import_data"]
        import_data["skip_indices"] = [0]
        session["import_data"] = import_data
        session.save()

        response = logged_client.post("/import/execute/")
        assert response.status_code == 200
        # Should still have only the pre-existing entry
        assert Entry.objects.filter(user=user).count() == 1
