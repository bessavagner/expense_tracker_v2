"""S12-5: real progress, and a failure that says what to do.

The eager task backend (CLOUD_TASKS_ENABLED unset) runs the handler inside the
request that enqueues it, so these tests see a finished job immediately. That is
the point of the eager backend, not a limitation of the test -- the attempt
accounting and the dead-letter decision are the same code in both modes.
"""

import io
from datetime import timedelta

import pytest
import time_machine
from django.core.management import call_command
from django.utils import timezone
from model_bakery import baker

from core.models import TaskRun
from finances.models import Entry, ImportJob, ImportStatus

_CSV = (
    b"data,valor,descri\xc3\xa7\xc3\xa3o,categoria,forma\n"
    b'01/03/2026,"R$ 42,00",Heineken,\xc3\x81lcool,Pix\n'
)
_MAPPING = {
    "date": "0",
    "amount": "1",
    "description": "2",
    "category": "3",
    "payment_method": "4",
}


@pytest.fixture
def seeded(household):
    baker.make("finances.Category", household=household, name="Álcool")
    baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    return household


def _to_preview(client, household):
    handle = io.BytesIO(_CSV)
    handle.name = "x.csv"
    client.post("/import/", data={"file": handle, "import_type": "regular"})
    job = ImportJob.objects.for_household(household).latest("created_at")
    client.post(f"/import/{job.id}/mapear/", data=_MAPPING)
    return job


@pytest.mark.django_db
class TestExecutionGoesThroughATask:
    def test_executing_enqueues_the_task_and_redirects_to_status(self, logged_client, seeded):
        job = _to_preview(logged_client, seeded)
        response = logged_client.post(f"/import/{job.id}/executar/")

        assert response.status_code == 302
        assert response.url == f"/import/{job.id}/status/"
        assert TaskRun.objects.filter(name="finances.run_import").count() == 1

    def test_the_eager_backend_actually_runs_it(self, logged_client, seeded):
        job = _to_preview(logged_client, seeded)
        logged_client.post(f"/import/{job.id}/executar/")
        job.refresh_from_db()

        assert job.status == ImportStatus.DONE
        assert Entry.objects.for_household(seeded).count() == 1

    def test_a_second_execute_does_not_enqueue_a_second_task(self, logged_client, seeded):
        """Idempotency by content hash: core.tasks.enqueue upserts on the key,
        so a double-tapped button is one TaskRun and one import."""
        job = _to_preview(logged_client, seeded)
        logged_client.post(f"/import/{job.id}/executar/")
        logged_client.post(f"/import/{job.id}/executar/")

        assert TaskRun.objects.filter(name="finances.run_import").count() == 1
        assert Entry.objects.for_household(seeded).count() == 1


@pytest.mark.django_db
class TestTheStatusPage:
    def test_it_shows_a_percentage_while_running(self, logged_client, seeded):
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.RUNNING,
            total_rows=200,
            processed_count=50,
            started_at=timezone.now(),
        )
        response = logged_client.get(f"/import/{job.id}/status/")
        assert response.status_code == 200
        assert "25" in response.content.decode()

    def test_it_stops_polling_once_the_job_is_finished(self, logged_client, seeded):
        """The response must not carry an hx-trigger once there is nothing left
        to poll for -- a page that polls forever is a page that keeps an
        instance warm for nothing."""
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.DONE,
            total_rows=1,
            processed_count=1,
            created_count=1,
        )
        response = logged_client.get(f"/import/{job.id}/status/")
        assert "hx-trigger" not in response.content.decode()

    def test_it_polls_while_there_is_still_something_to_wait_for(self, logged_client, seeded):
        """The other half. A status page that never polls shows a bar frozen at
        whatever it happened to read on first render."""
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.RUNNING,
            total_rows=200,
            processed_count=50,
            started_at=timezone.now(),
        )
        body = logged_client.get(f"/import/{job.id}/status/").content.decode()
        assert "hx-trigger" in body
        assert f"/import/{job.id}/status/" in body

    def test_the_htmx_fragment_is_the_fragment_alone(self, logged_client, seeded):
        """Polled responses swap one element; sending the whole page back would
        nest a second <html> inside the one already on screen."""
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.RUNNING,
            total_rows=10,
            processed_count=1,
            started_at=timezone.now(),
        )
        response = logged_client.get(f"/import/{job.id}/status/", headers={"HX-Request": "true"})
        body = response.content.decode()
        assert "<html" not in body
        assert 'id="import-progress"' in body

    def test_a_failed_job_says_what_to_do_in_ptbr(self, logged_client, seeded):
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.FAILED,
            error_message="Não foi possível ler o arquivo enviado. Envie novamente.",
        )
        body = logged_client.get(f"/import/{job.id}/status/").content.decode()
        assert "Não foi possível ler o arquivo enviado" in body

    def test_another_households_status_is_a_404(self, logged_client, seeded, other_household):
        job = baker.make(ImportJob, household=other_household)
        assert logged_client.get(f"/import/{job.id}/status/").status_code == 404


@pytest.mark.django_db
class TestStuckJobs:
    @time_machine.travel("2026-08-16 12:00:00+00:00", tick=False)
    def test_a_stuck_job_reads_as_failed_on_the_page_immediately(
        self, logged_client, seeded, settings
    ):
        """Without waiting for the sweep. The user is looking at the page now;
        telling them 'importando' about a job whose instance is gone is the
        indefinite spinner S12-5 exists to end."""
        settings.IMPORT_STUCK_AFTER_MINUTES = 15
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.RUNNING,
            started_at=timezone.now() - timedelta(minutes=30),
        )
        body = logged_client.get(f"/import/{job.id}/status/").content.decode()
        assert "interrompida" in body

    @time_machine.travel("2026-08-16 12:00:00+00:00", tick=False)
    def test_a_stuck_job_stops_the_page_polling(self, logged_client, seeded, settings):
        """Nothing will ever move the row again, so polling it is a request per
        two seconds for as long as the tab is open."""
        settings.IMPORT_STUCK_AFTER_MINUTES = 15
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.RUNNING,
            started_at=timezone.now() - timedelta(minutes=30),
        )
        assert "hx-trigger" not in logged_client.get(f"/import/{job.id}/status/").content.decode()

    @time_machine.travel("2026-08-16 12:00:00+00:00", tick=False)
    def test_the_sweep_marks_it_failed_with_a_reason(self, seeded, settings):
        settings.IMPORT_STUCK_AFTER_MINUTES = 15
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.RUNNING,
            started_at=timezone.now() - timedelta(minutes=30),
        )
        call_command("sweep_stuck_import_jobs")
        job.refresh_from_db()

        assert job.status == ImportStatus.FAILED
        assert job.error_message
        assert job.executed_at is not None

    @time_machine.travel("2026-08-16 12:00:00+00:00", tick=False)
    def test_the_sweep_leaves_a_healthy_running_job_alone(self, seeded, settings):
        settings.IMPORT_STUCK_AFTER_MINUTES = 15
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.RUNNING,
            started_at=timezone.now() - timedelta(minutes=2),
        )
        call_command("sweep_stuck_import_jobs")
        job.refresh_from_db()

        assert job.status == ImportStatus.RUNNING


@pytest.mark.django_db
class TestTheFailuresReport:
    def test_it_names_every_failed_line_and_why(self, logged_client, seeded):
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.DONE,
            error_count=2,
            failures=[
                {"line": 3, "reason": "Categoria 'Inexistente' não encontrada."},
                {"line": 9, "reason": "A linha foi recusada pelo banco de dados (DataError)."},
            ],
        )
        response = logged_client.get(f"/import/{job.id}/falhas.csv")

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
        body = response.content.decode("utf-8-sig")
        assert "linha,motivo" in body
        assert "3,Categoria 'Inexistente' não encontrada." in body
        assert "9," in body

    def test_it_says_how_many_more_there_were_when_truncated(self, logged_client, seeded):
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.DONE,
            error_count=1005,
            failures=[{"line": 2, "reason": "erro"}],
            failures_truncated=1004,
        )
        body = logged_client.get(f"/import/{job.id}/falhas.csv").content.decode("utf-8-sig")
        assert "1004" in body

    def test_a_job_with_no_failures_still_answers_a_valid_empty_report(self, logged_client, seeded):
        job = baker.make(ImportJob, household=seeded, status=ImportStatus.DONE)
        response = logged_client.get(f"/import/{job.id}/falhas.csv")
        assert response.status_code == 200
        assert "linha,motivo" in response.content.decode("utf-8-sig")

    def test_another_households_report_is_a_404(self, logged_client, seeded, other_household):
        job = baker.make(
            ImportJob, household=other_household, failures=[{"line": 2, "reason": "x"}]
        )
        assert logged_client.get(f"/import/{job.id}/falhas.csv").status_code == 404


@pytest.mark.django_db
class TestAJobCanNeverPollForever:
    """Review findings 1 and 4: every state the status page can be in either
    moves on its own or is reachable by the stuck sweep.

    Finding 1's mechanism: under the Cloud Tasks backend, `task_dispatch_view`
    runs the handler inside `transaction.atomic()` holding `select_for_update`
    on the TaskRun. If the instance dies mid-import that transaction rolls
    back — so anything the runner wrote about itself, including
    `status=RUNNING` and `started_at`, is gone. A job that only ever became
    RUNNING *inside* that transaction is therefore invisible to `is_stuck` and
    to `sweep_stuck_import_jobs`, and the page polls it forever.

    The fix is to commit QUEUED in the request that enqueues, which is a
    different transaction and survives.
    """

    def test_enqueuing_marks_the_job_queued_and_stamps_it(self, logged_client, seeded):
        job = _to_preview(logged_client, seeded)
        logged_client.post(f"/import/{job.id}/executar/")
        job.refresh_from_db()

        # The eager backend has already finished it; what matters is that
        # started_at was stamped by the enqueueing request, not by the runner.
        assert job.started_at is not None

    @time_machine.travel("2026-08-16 12:00:00+00:00", tick=False)
    def test_a_job_whose_handler_never_committed_is_still_swept(self, seeded, settings):
        """The exact aftermath of a rolled-back dispatch: QUEUED, stamped, and
        nothing will ever move it again."""
        settings.IMPORT_STUCK_AFTER_MINUTES = 15
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.QUEUED,
            started_at=timezone.now() - timedelta(minutes=30),
        )
        assert job.is_stuck

        call_command("sweep_stuck_import_jobs")
        job.refresh_from_db()
        assert job.status == ImportStatus.FAILED
        assert job.error_message

    @time_machine.travel("2026-08-16 12:00:00+00:00", tick=False)
    def test_a_freshly_queued_job_is_not_stuck(self, seeded, settings):
        settings.IMPORT_STUCK_AFTER_MINUTES = 15
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.QUEUED,
            started_at=timezone.now() - timedelta(minutes=2),
        )
        assert not job.is_stuck

    def test_a_job_that_was_never_executed_does_not_poll(self, logged_client, seeded):
        """Finding 4's other half. A `mapped` job has not been handed to
        anything, so there is no progress coming — the page must not sit there
        asking every two seconds until the tab is closed."""
        job = baker.make(ImportJob, household=seeded, status=ImportStatus.MAPPED, total_rows=5)
        body = logged_client.get(f"/import/{job.id}/status/").content.decode()
        assert "hx-trigger" not in body

    def test_a_queued_job_does_poll(self, logged_client, seeded):
        job = baker.make(
            ImportJob,
            household=seeded,
            status=ImportStatus.QUEUED,
            total_rows=5,
            started_at=timezone.now(),
        )
        assert "hx-trigger" in logged_client.get(f"/import/{job.id}/status/").content.decode()

    def test_remapping_a_finished_job_is_refused(self, logged_client, seeded):
        """Finding 4. Re-posting the mapping used to reset `done` → `mapped`;
        enqueue is idempotent on a permanent content hash, so nothing would
        ever dispatch again and the status page polled forever."""
        job = _to_preview(logged_client, seeded)
        logged_client.post(f"/import/{job.id}/executar/")
        job.refresh_from_db()
        assert job.status == ImportStatus.DONE

        response = logged_client.post(f"/import/{job.id}/mapear/", data=_MAPPING)
        job.refresh_from_db()

        assert response.status_code == 302
        assert response.url == f"/import/{job.id}/status/"
        assert job.status == ImportStatus.DONE, "a finished import was reopened"
        assert job.created_count == 1, "the finished job's counts were reset"
