"""A job the user cannot find is a job that did not survive."""

from datetime import timedelta

import pytest
import time_machine
from django.utils import timezone
from model_bakery import baker

from finances.models import ImportJob, ImportStatus


@pytest.mark.django_db
class TestImportHistory:
    def test_it_lists_this_households_jobs_newest_first(self, logged_client, household):
        with time_machine.travel("2026-08-14 09:00:00+00:00", tick=False):
            older = baker.make(
                ImportJob,
                household=household,
                original_filename="antigo.csv",
                status=ImportStatus.DONE,
                created_count=3,
            )
        with time_machine.travel("2026-08-16 09:00:00+00:00", tick=False):
            newer = baker.make(
                ImportJob,
                household=household,
                original_filename="recente.csv",
                status=ImportStatus.DONE,
                created_count=7,
            )

        body = logged_client.get("/import/historico/").content.decode()
        assert body.index("recente.csv") < body.index("antigo.csv")
        assert str(newer.created_count) in body
        assert str(older.created_count) in body

    def test_it_shows_what_each_one_did(self, logged_client, household):
        baker.make(
            ImportJob,
            household=household,
            original_filename="marco.csv",
            status=ImportStatus.DONE,
            created_count=41,
            skipped_count=2,
            error_count=1,
        )
        body = logged_client.get("/import/historico/").content.decode()
        assert "marco.csv" in body
        assert "41" in body and "2" in body and "1" in body

    def test_another_households_jobs_are_not_listed(
        self, logged_client, household, other_household
    ):
        baker.make(ImportJob, household=other_household, original_filename="alheio.csv")
        body = logged_client.get("/import/historico/").content.decode()
        assert "alheio.csv" not in body

    def test_an_empty_history_says_so_in_ptbr(self, logged_client, household):
        body = logged_client.get("/import/historico/").content.decode()
        assert "Nenhuma importação" in body

    def test_a_running_job_links_to_its_status_page(self, logged_client, household):
        job = baker.make(
            ImportJob,
            household=household,
            status=ImportStatus.RUNNING,
            started_at=timezone.now(),
        )
        body = logged_client.get("/import/historico/").content.decode()
        assert f"/import/{job.id}/status/" in body

    def test_a_job_with_errors_links_to_its_report(self, logged_client, household):
        job = baker.make(ImportJob, household=household, status=ImportStatus.DONE, error_count=4)
        body = logged_client.get("/import/historico/").content.decode()
        assert f"/import/{job.id}/falhas.csv" in body

    def test_it_is_capped_so_a_long_history_cannot_time_out_the_page(
        self, logged_client, household
    ):
        """50 is arbitrary but bounded, and the page says when it truncated
        rather than silently showing a prefix."""
        now = timezone.now()
        for index in range(55):
            baker.make(
                ImportJob,
                household=household,
                original_filename=f"f{index}.csv",
                status=ImportStatus.DONE,
            )
            ImportJob.objects.filter(original_filename=f"f{index}.csv").update(
                created_at=now - timedelta(minutes=index)
            )
        body = logged_client.get("/import/historico/").content.decode()
        assert "f0.csv" in body
        assert "f54.csv" not in body
        assert "Mostrando as 50" in body

    def test_unauthenticated_is_redirected(self):
        from django.test import Client

        assert Client().get("/import/historico/").status_code == 302
