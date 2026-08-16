"""Importing N rows must not cost O(N) closing-day lookups.

The importer resolves the card's closing day per row, and Entry.save() resolves
it again — both through a related-manager .filter(), which always queries. With
a prefetch and an in-Python filter the whole loop pays for it once.
"""

import io
from datetime import date

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from model_bakery import baker

from finances.models import Entry, PaymentMethod, PaymentMethodClosingDay
from finances.services.billing import resolve_closing_day

# Column order matches _MAPPING_REGULAR in test_views_importer.py: the importer
# maps by index, and parses pt-BR dates and "R$ 1.234,56" amounts.
_MAPPING_REGULAR = {
    "date": "0",
    "amount": "1",
    "description": "2",
    "category": "3",
    "payment_method": "4",
}


def _verb(query) -> str:
    return query["sql"].split()[0].upper()


def _count_verb(captured, verb: str) -> int:
    return sum(1 for query in captured.captured_queries if _verb(query) == verb)


def _data_statements(captured) -> int:
    """Everything except transaction control.

    SAVEPOINT and RELEASE are how the per-row atomic block is implemented, and
    ROLLBACK is how a rejected row is undone. None of them touch a table, so
    none of them are what "does importing N rows cost O(N) lookups?" is asking.
    """
    control = {"SAVEPOINT", "RELEASE", "ROLLBACK", "BEGIN", "COMMIT"}
    return sum(1 for query in captured.captured_queries if _verb(query) not in control)


def _csv(rows):
    header = "data,valor,descrição,categoria,forma\n"
    body = "".join(
        f'{1 + (i % 27):02d}/03/2026,"R$ {10 + i},00",compra {i},Alimentação,Crédito\n'
        for i in range(rows)
    )
    handle = io.BytesIO((header + body).encode())
    handle.name = "import.csv"
    return handle


@pytest.fixture
def import_fixtures(household):
    baker.make("finances.Category", household=household, name="Alimentação")
    return baker.make(
        "finances.PaymentMethod",
        household=household,
        name="Crédito",
        type="credit_card",
        closing_day=25,
    )


@pytest.mark.django_db
class TestResolveClosingDayUsesThePrefetchCache:
    def test_override_is_still_honoured(self, import_fixtures):
        pm = import_fixtures
        PaymentMethodClosingDay.objects.create(
            payment_method=pm, month=date(2026, 3, 1), closing_day=10
        )
        assert resolve_closing_day(pm, date(2026, 3, 15)) == 10

    def test_falls_back_to_the_default_closing_day(self, import_fixtures):
        pm = import_fixtures
        PaymentMethodClosingDay.objects.create(
            payment_method=pm, month=date(2026, 4, 1), closing_day=10
        )
        assert resolve_closing_day(pm, date(2026, 3, 15)) == 25

    def test_no_override_at_all(self, import_fixtures):
        assert resolve_closing_day(import_fixtures, date(2026, 3, 15)) == 25

    def test_a_prefetched_payment_method_costs_zero_queries(
        self, import_fixtures, django_assert_num_queries
    ):
        PaymentMethodClosingDay.objects.create(
            payment_method=import_fixtures, month=date(2026, 3, 1), closing_day=10
        )
        pm = (
            PaymentMethod.objects.filter(pk=import_fixtures.pk)
            .prefetch_related("monthly_closing_days")
            .first()
        )
        with django_assert_num_queries(0):
            for day in range(1, 21):
                resolve_closing_day(pm, date(2026, 3, day))


@pytest.mark.django_db
class TestImportQueryCount:
    """The gate: query count must be near-flat in the number of rows."""

    def _run_import(self, client, household, rows):
        from finances.models import ImportJob

        client.post("/import/", data={"file": _csv(rows), "import_type": "regular"})
        job_id = ImportJob.objects.for_household(household).latest("created_at").pk
        client.post(f"/import/{job_id}/mapear/", data=_MAPPING_REGULAR)
        return client.post(f"/import/{job_id}/executar/")

    def test_importing_more_rows_does_not_multiply_the_query_count(
        self, logged_client, household, import_fixtures
    ):
        """Compare 10 rows against 50 — the slope is what matters, not the value.

        An absolute bound would encode today's implementation. Measuring the
        marginal cost per row survives refactors and still catches an N+1.

        Counts data statements only. From E12 each row's write is wrapped in
        its own ``transaction.atomic()`` — the H5 fix — which emits a SAVEPOINT
        and a RELEASE per row. Those are transaction control, not lookups, and
        counting them here would turn this gate into an alarm that fires on the
        fix rather than on the defect it was written to catch. Their cost is
        asserted deliberately in the next test instead of hidden in this one.
        """
        with CaptureQueriesContext(connection) as small:
            self._run_import(logged_client, household, 10)
        small_count = _data_statements(small)

        Entry.objects.all().delete()

        with CaptureQueriesContext(connection) as large:
            self._run_import(logged_client, household, 50)
        large_count = _data_statements(large)

        per_row = (large_count - small_count) / 40
        assert per_row <= 1.5, (
            f"{per_row:.2f} data queries per imported row "
            f"(10 rows -> {small_count}, 50 rows -> {large_count})"
        )

    def test_the_lookup_cost_is_flat_not_merely_bounded(
        self, logged_client, household, import_fixtures
    ):
        """The E03 property stated directly: SELECTs must not grow with rows.

        The slope test above tolerates one write per row, which is right — but
        it would also tolerate one extra SELECT per row in exchange for one
        fewer INSERT. This does not: the closing-day prefetch means reading
        costs the same for 50 rows as for 10.
        """
        with CaptureQueriesContext(connection) as small:
            self._run_import(logged_client, household, 10)
        small_selects = _count_verb(small, "SELECT")

        Entry.objects.all().delete()

        with CaptureQueriesContext(connection) as large:
            self._run_import(logged_client, household, 50)
        large_selects = _count_verb(large, "SELECT")

        assert large_selects == small_selects, (
            f"reads grew with the file: {small_selects} SELECTs for 10 rows, "
            f"{large_selects} for 50 — the prefetch in import_runner regressed"
        )

    def test_each_row_costs_exactly_one_savepoint(self, logged_client, household, import_fixtures):
        """H5's price, written down where a future reader will find it.

        One SAVEPOINT and one RELEASE per row is what buys "one bad row fails
        alone". If this ever reads as zero, the per-row ``transaction.atomic()``
        has been removed and an IntegrityError will once again poison the whole
        import.
        """
        with CaptureQueriesContext(connection) as captured:
            self._run_import(logged_client, household, 50)

        # At least one per row, not exactly one: the request itself opens a
        # savepoint of its own, and pinning the total would couple this test to
        # Django's request handling rather than to the runner's loop.
        assert _count_verb(captured, "SAVEPOINT") >= 50
        assert _count_verb(captured, "RELEASE") >= 50

    def test_the_import_still_creates_the_entries(self, logged_client, household, import_fixtures):
        self._run_import(logged_client, household, 10)
        assert Entry.objects.count() == 10

    def test_billing_month_is_still_computed_from_the_closing_day(
        self, logged_client, household, import_fixtures
    ):
        """closing_day=25, so a purchase on 1 March closes in March and is paid
        in April — ``compute_billing_month`` returns 2026-04-01."""
        self._run_import(logged_client, household, 10)
        entry = Entry.objects.filter(date=date(2026, 3, 1)).first()
        assert entry is not None
        assert entry.billing_month == date(2026, 4, 1)
