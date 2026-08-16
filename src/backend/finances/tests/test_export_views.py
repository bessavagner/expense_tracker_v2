"""Requesting an export, and the link that delivers it."""

import io
import zipfile

import pytest
import time_machine
from django.test import Client
from model_bakery import baker

from core.downloads import sign_download
from core.models import TaskRun
from finances.models import ExportJob, ExportStatus


@pytest.fixture
def populated(household, user):
    from datetime import date
    from decimal import Decimal

    category = baker.make("finances.Category", household=household, name="Alimentação")
    payment = baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    baker.make(
        "finances.Entry",
        household=household,
        created_by=user,
        date=date(2026, 3, 1),
        amount=Decimal("42.00"),
        description="Feira",
        category=category,
        payment_method=payment,
        entry_type="regular",
        billing_month=date(2026, 3, 1),
    )
    return household


@pytest.mark.django_db
class TestRequestingAnExport:
    def test_requesting_enqueues_a_task_and_redirects(self, logged_client, populated):
        response = logged_client.post("/exportar/solicitar/")
        assert response.status_code == 302
        assert response.url == "/exportar/"
        assert TaskRun.objects.filter(name="finances.build_export").count() == 1

    def test_the_eager_backend_builds_it(self, logged_client, populated):
        logged_client.post("/exportar/solicitar/")
        job = ExportJob.objects.for_household(populated).latest("created_at")

        assert job.status == ExportStatus.DONE
        assert job.storage_key
        assert job.size_bytes > 0

    def test_the_stored_object_is_a_readable_archive(self, logged_client, populated):
        from core.storage import job_storage

        logged_client.post("/exportar/solicitar/")
        job = ExportJob.objects.for_household(populated).latest("created_at")
        with job_storage().open(job.storage_key) as handle:
            archive = zipfile.ZipFile(io.BytesIO(handle.read()))
        assert "entradas.csv" in archive.namelist()

    def test_a_second_request_makes_a_second_job(self, logged_client, populated):
        """Each request is a genuinely new export -- the household's data may
        have changed since the last one, so deduplicating them would hand the
        user a stale archive."""
        logged_client.post("/exportar/solicitar/")
        logged_client.post("/exportar/solicitar/")
        assert ExportJob.objects.for_household(populated).count() == 2

    def test_the_export_lands_under_the_export_prefix(self, logged_client, populated):
        from core.storage import JOB_EXPORT_PREFIX

        logged_client.post("/exportar/solicitar/")
        job = ExportJob.objects.for_household(populated).latest("created_at")
        assert job.storage_key.startswith(f"{JOB_EXPORT_PREFIX}/{populated.id}/")

    def test_another_households_data_is_not_in_the_archive(
        self, logged_client, populated, other_household
    ):
        from datetime import date
        from decimal import Decimal

        from core.storage import job_storage

        baker.make(
            "finances.Entry",
            household=other_household,
            description="ALHEIO",
            amount=Decimal("1.00"),
            date=date(2026, 3, 1),
            billing_month=date(2026, 3, 1),
        )
        logged_client.post("/exportar/solicitar/")
        job = ExportJob.objects.for_household(populated).latest("created_at")
        with job_storage().open(job.storage_key) as handle:
            archive = zipfile.ZipFile(io.BytesIO(handle.read()))
        for name in archive.namelist():
            assert b"ALHEIO" not in archive.read(name)


@pytest.mark.django_db
class TestDownloading:
    def _finished_job(self, client, household):
        client.post("/exportar/solicitar/")
        return ExportJob.objects.for_household(household).latest("created_at")

    def test_a_valid_link_serves_the_archive(self, logged_client, populated):
        job = self._finished_job(logged_client, populated)
        response = logged_client.get(f"/exportar/baixar/{job.download_token}/")

        assert response.status_code == 200
        assert response["Content-Type"] == "application/zip"
        assert "attachment" in response["Content-Disposition"]
        archive = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
        assert "ledger.json" in archive.namelist()

    def test_an_expired_link_is_a_404(self, logged_client, populated, settings):
        """The DoD's 'export URLs expire, verified by test', asserted through
        the real view rather than only through the signer."""
        settings.EXPORT_URL_MAX_AGE_SECONDS = 3600
        with time_machine.travel("2026-08-16 12:00:00+00:00", tick=False):
            job = self._finished_job(logged_client, populated)
            token = job.download_token
        with time_machine.travel("2026-08-16 13:00:01+00:00", tick=False):
            assert logged_client.get(f"/exportar/baixar/{token}/").status_code == 404

    def test_a_forged_token_is_a_404(self, logged_client, populated):
        assert logged_client.get("/exportar/baixar/nonsense/").status_code == 404

    def test_a_token_for_another_kind_is_a_404(self, logged_client, populated):
        job = self._finished_job(logged_client, populated)
        assert (
            logged_client.get(f"/exportar/baixar/{sign_download('import', job.id)}/").status_code
            == 404
        )

    def test_another_household_cannot_use_a_valid_token(
        self, logged_client, populated, other_user, other_household
    ):
        """The link expires AND the household is checked. Either alone would be
        one mistake away from another family's complete financial history."""
        job = self._finished_job(logged_client, populated)
        intruder = Client()
        intruder.force_login(other_user)
        assert intruder.get(f"/exportar/baixar/{job.download_token}/").status_code == 404

    def test_an_unfinished_job_cannot_be_downloaded(self, logged_client, populated):
        job = baker.make(ExportJob, household=populated, status=ExportStatus.RUNNING)
        assert logged_client.get(f"/exportar/baixar/{job.download_token}/").status_code == 404

    def test_an_expired_object_is_a_404_even_though_the_row_survives(
        self, logged_client, populated
    ):
        """The 7-day lifecycle rule deletes the object; the ExportJob row
        outlives it deliberately, so 'gerada em 3 de agosto' plus a 404 tells
        the user the file expired rather than that it never existed."""
        from core.storage import job_storage

        job = self._finished_job(logged_client, populated)
        job_storage().delete(job.storage_key)
        assert logged_client.get(f"/exportar/baixar/{job.download_token}/").status_code == 404

    def test_unauthenticated_is_redirected_not_served(self, logged_client, populated):
        job = self._finished_job(logged_client, populated)
        assert Client().get(f"/exportar/baixar/{job.download_token}/").status_code == 302


@pytest.mark.django_db
class TestTheExportPage:
    def test_it_lists_this_households_exports_with_a_link(self, logged_client, populated):
        logged_client.post("/exportar/solicitar/")
        body = logged_client.get("/exportar/").content.decode()
        assert "/exportar/baixar/" in body

    def test_it_says_the_link_expires(self, logged_client, populated):
        logged_client.post("/exportar/solicitar/")
        assert "expira" in logged_client.get("/exportar/").content.decode().lower()

    def test_another_households_exports_are_not_listed(
        self, logged_client, populated, other_household
    ):
        baker.make(
            ExportJob,
            household=other_household,
            status=ExportStatus.DONE,
            storage_key="exports/outro/alheio.zip",
        )
        assert "alheio" not in logged_client.get("/exportar/").content.decode()

    def test_an_empty_page_says_so_in_ptbr(self, logged_client, household):
        assert "Nenhuma exportação" in logged_client.get("/exportar/").content.decode()

    def test_unauthenticated_is_redirected(self):
        assert Client().get("/exportar/").status_code == 302
