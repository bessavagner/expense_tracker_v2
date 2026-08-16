"""What the job promises the views and the runner."""

from datetime import timedelta

import pytest
import time_machine
from django.test import override_settings
from django.utils import timezone
from model_bakery import baker

from finances.models import ImportJob, ImportStatus


@pytest.mark.django_db
class TestImportJobState:
    def test_a_new_job_is_uploaded_and_unfinished(self, household):
        job = baker.make(ImportJob, household=household)
        assert job.status == ImportStatus.UPLOADED
        assert not job.is_finished

    @pytest.mark.parametrize("status", [ImportStatus.DONE, ImportStatus.FAILED])
    def test_done_and_failed_are_finished(self, household, status):
        job = baker.make(ImportJob, household=household, status=status)
        assert job.is_finished

    def test_progress_is_zero_when_nothing_is_known_yet(self, household):
        job = baker.make(ImportJob, household=household, total_rows=0, processed_count=0)
        assert job.progress_percent == 0

    def test_progress_is_a_whole_percentage(self, household):
        job = baker.make(ImportJob, household=household, total_rows=8, processed_count=3)
        assert job.progress_percent == 37

    def test_progress_never_exceeds_one_hundred(self, household):
        """A retry that re-counts must not render a 140% bar."""
        job = baker.make(ImportJob, household=household, total_rows=8, processed_count=99)
        assert job.progress_percent == 100


@pytest.mark.django_db
class TestStuckDetection:
    @override_settings(IMPORT_STUCK_AFTER_MINUTES=15)
    @time_machine.travel("2026-08-16 12:00:00+00:00", tick=False)
    def test_a_recently_started_job_is_not_stuck(self, household):
        job = baker.make(
            ImportJob,
            household=household,
            status=ImportStatus.RUNNING,
            started_at=timezone.now() - timedelta(minutes=14),
        )
        assert not job.is_stuck

    @override_settings(IMPORT_STUCK_AFTER_MINUTES=15)
    @time_machine.travel("2026-08-16 12:00:00+00:00", tick=False)
    def test_a_long_running_job_is_stuck(self, household):
        job = baker.make(
            ImportJob,
            household=household,
            status=ImportStatus.RUNNING,
            started_at=timezone.now() - timedelta(minutes=16),
        )
        assert job.is_stuck

    @override_settings(IMPORT_STUCK_AFTER_MINUTES=15)
    @time_machine.travel("2026-08-16 12:00:00+00:00", tick=False)
    def test_a_finished_job_is_never_stuck(self, household):
        job = baker.make(
            ImportJob,
            household=household,
            status=ImportStatus.DONE,
            started_at=timezone.now() - timedelta(days=3),
        )
        assert not job.is_stuck


@pytest.mark.django_db
class TestFailureRecording:
    def test_a_failure_is_recorded_with_its_line_and_reason(self, household):
        job = baker.make(ImportJob, household=household)
        job.record_failure(7, "Categoria não encontrada")
        assert job.failures == [{"line": 7, "reason": "Categoria não encontrada"}]
        assert job.failures_truncated == 0

    def test_recording_stops_at_the_cap_but_the_count_stays_exact(self, household):
        """Individually reported up to the cap; beyond it, honest about how many
        more there were. An unbounded JSONField on a pooled connection is the
        alternative, and a 20 000-row file that fails entirely would write
        megabytes into one row."""
        job = baker.make(ImportJob, household=household)
        for line in range(ImportJob.MAX_RECORDED_FAILURES + 5):
            job.record_failure(line, "erro")
        assert len(job.failures) == ImportJob.MAX_RECORDED_FAILURES
        assert job.failures_truncated == 5
