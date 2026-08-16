import io
from datetime import date as dt

import pytest
from django.test import Client
from model_bakery import baker

from finances.models import Entry, ImportJob, InstallmentPlan

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

# Not a UUID any job will ever have. The wizard's steps are job-scoped now, so
# "no state" is a 404 on a job id rather than a redirect on an empty session.
_MISSING_JOB = "00000000-0000-4000-8000-000000000000"


def _job_id(household):
    return ImportJob.objects.for_household(household).latest("created_at").pk


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
    def _upload_first(self, logged_client, household):
        csv_file = io.BytesIO(_SIMPLE_CSV)
        csv_file.name = "test.csv"
        logged_client.post("/import/", data={"file": csv_file, "import_type": "regular"})
        return _job_id(household)

    def test_mapping_page_renders(self, logged_client, household):
        job_id = self._upload_first(logged_client, household)
        response = logged_client.get(f"/import/{job_id}/mapear/")
        assert response.status_code == 200
        assert "mapping" in response.context

    def test_mapping_auto_detects_columns(self, logged_client, household):
        job_id = self._upload_first(logged_client, household)
        response = logged_client.get(f"/import/{job_id}/mapear/")
        mapping = response.context["mapping"]
        assert mapping["date"] == 0
        assert mapping["amount"] == 1
        assert mapping["description"] == 2

    def test_confirm_mapping_redirects_to_preview(self, logged_client, household):
        job_id = self._upload_first(logged_client, household)
        response = logged_client.post(f"/import/{job_id}/mapear/", data=_MAPPING_REGULAR)
        assert response.status_code == 302  # redirects to preview

    def test_an_unknown_job_is_a_404(self, logged_client):
        """Was `test_no_session_redirects_to_upload`. There is no session to be
        missing any more, so the equivalent failure is an id that names no job
        this household owns."""
        assert logged_client.get(f"/import/{_MISSING_JOB}/mapear/").status_code == 404


@pytest.mark.django_db
class TestImportPreviewView:
    def _to_preview(self, logged_client, household):
        """Upload and map a CSV to get to the preview step."""
        baker.make("finances.Category", household=household, name="Álcool")
        baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
        csv_content = (
            b"data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n"
            b'01/03/2026,"R$ 42,00",Heineken,\xc3\x81lcool,Pix\n'
            b'02/03/2026,"R$ 14,00",Disk Bebida,NewCat,Pix\n'
        )
        csv_file = io.BytesIO(csv_content)
        csv_file.name = "test.csv"
        logged_client.post("/import/", data={"file": csv_file, "import_type": "regular"})
        job_id = _job_id(household)
        logged_client.post(f"/import/{job_id}/mapear/", data=_MAPPING_REGULAR)
        return job_id

    def test_preview_page_renders(self, logged_client, household):
        job_id = self._to_preview(logged_client, household)
        response = logged_client.get(f"/import/{job_id}/preview/")
        assert response.status_code == 200
        assert "rows" in response.context

    def test_preview_shows_unmatched_categories(self, logged_client, household):
        job_id = self._to_preview(logged_client, household)
        response = logged_client.get(f"/import/{job_id}/preview/")
        assert "NewCat" in response.context["unmatched_categories"]

    def test_an_unknown_job_is_a_404(self, logged_client):
        assert logged_client.get(f"/import/{_MISSING_JOB}/preview/").status_code == 404

    def test_an_unmapped_job_goes_back_to_the_mapping_step(self, logged_client, household):
        """Reaching preview before confirming a mapping has nothing to show."""
        csv_file = io.BytesIO(_SIMPLE_CSV)
        csv_file.name = "test.csv"
        logged_client.post("/import/", data={"file": csv_file, "import_type": "regular"})
        job_id = _job_id(household)
        response = logged_client.get(f"/import/{job_id}/preview/")
        assert response.status_code == 302
        assert response.url == f"/import/{job_id}/mapear/"


@pytest.mark.django_db
class TestImportExecuteView:
    def _to_preview(self, logged_client, household):
        baker.make("finances.Category", household=household, name="Álcool")
        baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
        csv_content = (
            b"data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n"
            b'01/03/2026,"R$ 42,00",Heineken,\xc3\x81lcool,Pix\n'
            b'05/03/2026,"R$ 14,00",Disk Bebida,\xc3\x81lcool,Pix\n'
        )
        csv_file = io.BytesIO(csv_content)
        csv_file.name = "test.csv"
        logged_client.post("/import/", data={"file": csv_file, "import_type": "regular"})
        job_id = _job_id(household)
        logged_client.post(f"/import/{job_id}/mapear/", data=_MAPPING_REGULAR)
        return job_id

    def test_execute_creates_entries(self, logged_client, household):
        job_id = self._to_preview(logged_client, household)
        response = logged_client.post(f"/import/{job_id}/executar/")
        assert response.status_code == 302
        assert Entry.objects.for_household(household).count() == 2

    def test_execute_entries_have_correct_billing_month(self, logged_client, household):
        job_id = self._to_preview(logged_client, household)
        logged_client.post(f"/import/{job_id}/executar/")
        entry = Entry.objects.for_household(household).filter(description="Heineken").first()
        assert entry is not None
        assert entry.billing_month == dt(2026, 3, 1)

    def test_execute_installments(self, logged_client, household):
        baker.make("finances.Category", household=household, name="Roupa")
        baker.make(
            "finances.PaymentMethod",
            household=household,
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
        job_id = _job_id(household)
        logged_client.post(
            f"/import/{job_id}/mapear/",
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
        response = logged_client.post(f"/import/{job_id}/executar/")
        assert response.status_code == 302
        assert InstallmentPlan.objects.for_household(household).count() == 1
        assert Entry.objects.for_household(household).filter(entry_type="installment").count() == 2

    def test_execute_skips_duplicates_marked_for_skip(self, logged_client, household):
        cat = baker.make("finances.Category", household=household, name="Álcool")
        pm = baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
        # Pre-existing entry
        baker.make(
            "finances.Entry",
            household=household,
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
        job_id = _job_id(household)
        logged_client.post(f"/import/{job_id}/mapear/", data=_MAPPING_REGULAR)
        # Mark the duplicate for skip. Line 2, because line 1 is the header --
        # the skip is keyed by CSV line number now, not by list index.
        logged_client.post(f"/import/{job_id}/preview/", data={"skip_2": "on"})

        response = logged_client.post(f"/import/{job_id}/executar/")
        assert response.status_code == 302
        # Should still have only the pre-existing entry
        assert Entry.objects.for_household(household).count() == 1
