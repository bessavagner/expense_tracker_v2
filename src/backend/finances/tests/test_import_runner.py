"""H5: one bad row must not kill the rows after it.

The test forces a *real* database error rather than raising IntegrityError from
Python, and the difference is the whole point. A Python-level exception leaves
the Postgres transaction perfectly healthy, so a test that raises one passes
whether or not savepoints exist -- it would assert nothing. A description longer
than the column is rejected by Postgres itself, which marks the transaction
aborted; every statement after it then raises TransactionManagementError until
something rolls back to a savepoint. That is the production failure, reproduced.
"""

import pytest
from model_bakery import baker

from finances.models import Entry, ImportJob, ImportStatus
from finances.services.import_runner import run_import
from finances.services.import_storage import store_upload

_TOO_LONG = "x" * 600  # Entry.description is CharField(max_length=500)


def _job(household, user, body: str, import_type="regular"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    header = "data,valor,descrição,categoria,forma\n"
    upload = SimpleUploadedFile("x.csv", (header + body).encode(), "text/csv")
    job = ImportJob.objects.create(
        household=household,
        created_by=user,
        import_type=import_type,
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
    from finances.services.import_rows import rows_for

    job.total_rows = len(rows_for(job, mark_duplicates=False))
    job.save(update_fields=["total_rows"])
    return job


@pytest.fixture
def seeded(household):
    baker.make("finances.Category", household=household, name="Alimentação")
    baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    return household


def _run_as_production_does(job):
    """Run the import inside an outer transaction, the way a task does.

    This is not incidental -- it is what makes these tests mean anything.
    ``core/tasks/views.py`` holds ``select_for_update`` on the TaskRun row for
    the whole handler, so ``run_import`` always executes inside an open
    transaction in production. That is the only context in which H5 exists: a
    statement Postgres rejects marks *the transaction* aborted, and every later
    statement then raises TransactionManagementError until something rolls back
    to a savepoint.

    Call it without an outer transaction and each INSERT is its own autocommit
    statement, so a rejected row poisons nothing and these tests pass whether
    or not the per-row savepoint exists -- asserting precisely nothing. Verified
    by removing the ``transaction.atomic()`` in ``_create_one``: with this
    wrapper the suite fails with TransactionManagementError; without it, green.
    """
    from django.db import transaction

    with transaction.atomic():
        run_import(job)


@pytest.mark.django_db(transaction=True)
class TestOneBadRowDoesNotPoisonTheRest:
    def test_the_rows_after_a_database_error_still_land(self, seeded, user):
        job = _job(
            seeded,
            user,
            '01/03/2026,"R$ 10,00",Primeira,Alimentação,Pix\n'
            f'02/03/2026,"R$ 20,00",{_TOO_LONG},Alimentação,Pix\n'
            '03/03/2026,"R$ 30,00",Terceira,Alimentação,Pix\n',
        )
        _run_as_production_does(job)

        descriptions = set(
            Entry.objects.for_household(seeded).values_list("description", flat=True)
        )
        assert descriptions == {"Primeira", "Terceira"}

    def test_the_counts_are_accurate_rather_than_misleading(self, seeded, user):
        job = _job(
            seeded,
            user,
            '01/03/2026,"R$ 10,00",Primeira,Alimentação,Pix\n'
            f'02/03/2026,"R$ 20,00",{_TOO_LONG},Alimentação,Pix\n'
            '03/03/2026,"R$ 30,00",Terceira,Alimentação,Pix\n',
        )
        _run_as_production_does(job)
        job.refresh_from_db()

        assert job.created_count == 2
        assert job.error_count == 1
        assert job.skipped_count == 0
        assert job.status == ImportStatus.DONE

    def test_the_failed_row_says_which_line_and_why(self, seeded, user):
        job = _job(
            seeded,
            user,
            '01/03/2026,"R$ 10,00",Primeira,Alimentação,Pix\n'
            f'02/03/2026,"R$ 20,00",{_TOO_LONG},Alimentação,Pix\n',
        )
        _run_as_production_does(job)
        job.refresh_from_db()

        assert len(job.failures) == 1
        assert job.failures[0]["line"] == 3  # header is line 1
        assert job.failures[0]["reason"]


@pytest.mark.django_db
class TestResolutionAndSkipping:
    def test_an_unknown_category_fails_that_row_with_a_ptbr_reason(self, seeded, user):
        job = _job(seeded, user, '01/03/2026,"R$ 10,00",Compra,Inexistente,Pix\n')
        run_import(job)
        job.refresh_from_db()

        assert job.created_count == 0
        assert job.error_count == 1
        assert "Categoria" in job.failures[0]["reason"]

    def test_a_new_category_resolution_creates_it_once(self, seeded, user):
        from finances.models import Category

        job = _job(
            seeded,
            user,
            '01/03/2026,"R$ 10,00",A,Nova,Pix\n02/03/2026,"R$ 20,00",B,Nova,Pix\n',
        )
        job.category_resolutions = {"Nova": "__new__"}
        job.save(update_fields=["category_resolutions"])
        run_import(job)
        job.refresh_from_db()

        assert job.created_count == 2
        assert Category.objects.for_household(seeded).filter(name="Nova").count() == 1

    def test_a_skipped_line_is_counted_as_skipped_not_failed(self, seeded, user):
        job = _job(
            seeded,
            user,
            '01/03/2026,"R$ 10,00",A,Alimentação,Pix\n02/03/2026,"R$ 20,00",B,Alimentação,Pix\n',
        )
        job.skip_lines = [3]
        job.save(update_fields=["skip_lines"])
        run_import(job)
        job.refresh_from_db()

        assert (job.created_count, job.skipped_count, job.error_count) == (1, 1, 0)


@pytest.mark.django_db
class TestIdempotence:
    def test_re_running_the_same_job_creates_nothing_new(self, seeded, user):
        """The DoD's 'a test proves re-running the same import creates no
        duplicates'. A finished job refuses to run again; the guard is on the
        row, so it holds across processes."""
        job = _job(seeded, user, '01/03/2026,"R$ 10,00",A,Alimentação,Pix\n')
        run_import(job)
        run_import(job)
        job.refresh_from_db()

        assert Entry.objects.for_household(seeded).count() == 1
        assert job.created_count == 1

    def test_a_second_upload_of_the_same_file_is_flagged_duplicate_at_preview(self, seeded, user):
        """The other half of idempotence, and the one that survived the
        refactor: the file can be re-uploaded, and the preview marks the rows
        the household already has."""
        from finances.services.import_rows import rows_for

        first = _job(seeded, user, '01/03/2026,"R$ 10,00",A,Alimentação,Pix\n')
        run_import(first)

        second = _job(seeded, user, '01/03/2026,"R$ 10,00",A,Alimentação,Pix\n')
        assert [row["status"] for row in rows_for(second)] == ["duplicate"]


@pytest.mark.django_db
class TestWholeJobFailure:
    def test_a_missing_file_leaves_the_job_failed_with_a_ptbr_reason(self, seeded, user):
        """Not RUNNING forever. The file is gone -- the 7-day lifecycle rule
        reached it, or it was never written -- and the user needs to be told
        what to do, not shown a bar that never moves."""
        job = _job(seeded, user, '01/03/2026,"R$ 10,00",A,Alimentação,Pix\n')
        job.storage_key = "imports/nope/missing.csv"
        job.save(update_fields=["storage_key"])

        run_import(job)
        job.refresh_from_db()

        assert job.status == ImportStatus.FAILED
        assert job.executed_at is not None
        assert "Envie a planilha novamente" in job.error_message


@pytest.mark.django_db
class TestDuplicatesAreNotImported:
    """Review finding 3. The preview badges a row "Dup" and excludes it from
    "Importar N entradas →"; the runner must agree, or the button lies and the
    family's ledger doubles.

    This is the recovery flow the stuck-import and failed-import messages both
    advertise — "send the file again, the rows you already have will be marked
    as duplicates" — so it has to hold without the user ticking 400 checkboxes.
    """

    def test_a_row_already_in_the_ledger_is_skipped_not_created(self, seeded, user):
        first = _job(seeded, user, '01/03/2026,"R$ 10,00",A,Alimentação,Pix\n')
        run_import(first)
        assert Entry.objects.for_household(seeded).count() == 1

        second = _job(seeded, user, '01/03/2026,"R$ 10,00",A,Alimentação,Pix\n')
        run_import(second)
        second.refresh_from_db()

        assert Entry.objects.for_household(seeded).count() == 1, "the duplicate was imported"
        assert (second.created_count, second.skipped_count, second.error_count) == (0, 1, 0)

    def test_a_partial_re_upload_imports_only_what_is_new(self, seeded, user):
        """The real shape of the recovery: an import died halfway, the user
        sends the whole file again, and only the missing rows land."""
        first = _job(seeded, user, '01/03/2026,"R$ 10,00",A,Alimentação,Pix\n')
        run_import(first)

        second = _job(
            seeded,
            user,
            '01/03/2026,"R$ 10,00",A,Alimentação,Pix\n'
            '02/03/2026,"R$ 20,00",B,Alimentação,Pix\n'
            '03/03/2026,"R$ 30,00",C,Alimentação,Pix\n',
        )
        run_import(second)
        second.refresh_from_db()

        assert Entry.objects.for_household(seeded).count() == 3
        assert (second.created_count, second.skipped_count) == (2, 1)

    def test_two_identical_rows_in_one_file_both_land(self, seeded, user):
        """Not everything that looks like a duplicate is one. Production holds
        two genuine R$ 20 fuel purchases on the same day with the same
        description; duplicates are judged against what was in the ledger
        *before* the run, so a file may legitimately repeat itself."""
        job = _job(
            seeded,
            user,
            '01/03/2026,"R$ 20,00",Gasolina,Alimentação,Pix\n'
            '01/03/2026,"R$ 20,00",Gasolina,Alimentação,Pix\n',
        )
        run_import(job)
        job.refresh_from_db()

        assert Entry.objects.for_household(seeded).count() == 2
        assert (job.created_count, job.skipped_count) == (2, 0)
