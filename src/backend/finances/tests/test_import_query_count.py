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

    def _run_import(self, client, rows):
        client.post("/import/", data={"file": _csv(rows), "import_type": "regular"})
        client.post("/import/map/", data=_MAPPING_REGULAR)
        return client.post("/import/execute/")

    def test_importing_more_rows_does_not_multiply_the_query_count(
        self, logged_client, import_fixtures
    ):
        """Compare 10 rows against 50 — the slope is what matters, not the value.

        An absolute bound would encode today's implementation. Measuring the
        marginal cost per row survives refactors and still catches an N+1.
        """
        with CaptureQueriesContext(connection) as small:
            self._run_import(logged_client, 10)
        small_count = len(small.captured_queries)

        Entry.objects.all().delete()

        with CaptureQueriesContext(connection) as large:
            self._run_import(logged_client, 50)
        large_count = len(large.captured_queries)

        per_row = (large_count - small_count) / 40
        assert per_row <= 1.5, (
            f"{per_row:.2f} queries per imported row "
            f"(10 rows -> {small_count}, 50 rows -> {large_count})"
        )

    def test_the_import_still_creates_the_entries(self, logged_client, import_fixtures):
        self._run_import(logged_client, 10)
        assert Entry.objects.count() == 10

    def test_billing_month_is_still_computed_from_the_closing_day(
        self, logged_client, import_fixtures
    ):
        """closing_day=25, so a purchase on 1 March closes in March and is paid
        in April — ``compute_billing_month`` returns 2026-04-01."""
        self._run_import(logged_client, 10)
        entry = Entry.objects.filter(date=date(2026, 3, 1)).first()
        assert entry is not None
        assert entry.billing_month == date(2026, 4, 1)
