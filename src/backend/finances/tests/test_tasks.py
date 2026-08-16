"""The task handlers' edge paths: gone, already done, and failed.

These are the branches nobody exercises by using the product, which is exactly
why they are worth a test -- each one is what a retried or redelivered task
lands in, and getting them wrong means either a duplicated import or a job that
claims to be running forever.
"""

import pytest
from model_bakery import baker

from finances.models import ExportJob, ExportStatus, ImportJob, ImportStatus
from finances.tasks import build_export_task, run_import_task


@pytest.mark.django_db
class TestRunImportTask:
    def test_a_job_that_no_longer_exists_is_a_completed_task_not_a_failed_one(self):
        """Deleted between enqueue and dispatch. Retrying cannot bring it back,
        so raising here would burn attempts and then dead-letter for nothing."""
        run_import_task({"job_id": "00000000-0000-4000-8000-000000000000"})

    def test_it_runs_the_job_it_is_given(self, household, user, tmp_path):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from finances.models import Entry
        from finances.services.import_storage import store_upload

        baker.make("finances.Category", household=household, name="Alimentação")
        baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
        body = 'data,valor,descrição,categoria,forma\n01/03/2026,"R$ 10,00",A,Alimentação,Pix\n'
        upload = SimpleUploadedFile("x.csv", body.encode(), "text/csv")
        job = ImportJob.objects.create(
            household=household,
            created_by=user,
            storage_key=store_upload(upload, household.id),
            column_mapping={
                "date": 0,
                "amount": 1,
                "description": 2,
                "category": 3,
                "payment_method": 4,
            },
            status=ImportStatus.MAPPED,
        )

        run_import_task({"job_id": str(job.id)})
        job.refresh_from_db()

        assert job.status == ImportStatus.DONE
        assert Entry.objects.for_household(household).count() == 1


@pytest.mark.django_db
class TestBuildExportTask:
    def test_a_job_that_no_longer_exists_is_a_completed_task(self):
        build_export_task({"job_id": "00000000-0000-4000-8000-000000000000"})

    def test_an_already_built_export_is_not_rebuilt(self, household, user):
        """max_attempts=3 means this handler can be redelivered. Rebuilding
        would write a second object and orphan the first under the same
        7-day rule."""
        job = baker.make(
            ExportJob,
            household=household,
            created_by=user,
            status=ExportStatus.DONE,
            storage_key="exports/already/there.zip",
            size_bytes=123,
        )
        build_export_task({"job_id": str(job.id)})
        job.refresh_from_db()

        assert job.storage_key == "exports/already/there.zip"
        assert job.size_bytes == 123

    def test_a_failure_leaves_a_ptbr_reason_and_re_raises_for_the_retry(
        self, household, user, monkeypatch
    ):
        """Both halves matter. The row must carry something the user can read,
        and the exception must escape so core.tasks counts the attempt and
        eventually dead-letters into Sentry."""
        from finances import tasks

        def exploding_build(_household):
            raise RuntimeError("bucket on fire")

        monkeypatch.setattr("finances.services.export_builder.build_export", exploding_build)
        assert tasks.BUILD_EXPORT  # the name is part of the registry contract

        job = baker.make(
            ExportJob, household=household, created_by=user, status=ExportStatus.PENDING
        )
        with pytest.raises(RuntimeError):
            build_export_task({"job_id": str(job.id)})

        job.refresh_from_db()
        assert job.status == ExportStatus.FAILED
        assert "Não foi possível gerar a exportação" in job.error_message
        assert job.storage_key == ""
