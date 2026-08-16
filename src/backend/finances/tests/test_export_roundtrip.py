"""The DoD's hardest assertion: an export this product can read back.

Scoped honestly. The claim is not "two households become byte-identical" --
ids, timestamps and derived averages are not portable and should not be. The
claim is that the *money* survives: the sum of what the ledger holds, and the
per-category split of it, are the same on both sides.
"""

import csv as csv_module
import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from model_bakery import baker

from finances.models import Category, Entry, ImportJob, PaymentMethod
from finances.services.export_builder import build_export

_MAPPING = {
    "date": "0",
    "amount": "1",
    "description": "2",
    "category": "3",
    "payment_method": "4",
}


@pytest.fixture
def source(household, user):
    """A household with money in it, across two categories and two payment
    methods, including a negative amount and a value with a thousands part."""
    food = baker.make("finances.Category", household=household, name="Alimentação")
    fuel = baker.make("finances.Category", household=household, name="Combustível")
    pix = baker.make("finances.PaymentMethod", household=household, name="Pix", type="pix")
    card = baker.make(
        "finances.PaymentMethod",
        household=household,
        name="Crédito C6",
        type="credit_card",
        closing_day=25,
    )

    rows = [
        (date(2026, 3, 1), Decimal("1234.56"), "Mercado do mês", food, card),
        (date(2026, 3, 4), Decimal("42.00"), "Feira", food, pix),
        (date(2026, 3, 9), Decimal("-226.21"), "Estorno combustível", fuel, card),
        (date(2026, 3, 11), Decimal("310.90"), "Posto", fuel, pix),
    ]
    for day, amount, description, category, payment in rows:
        baker.make(
            "finances.Entry",
            household=household,
            created_by=user,
            date=day,
            amount=amount,
            description=description,
            category=category,
            payment_method=payment,
            entry_type="regular",
            billing_month=date(2026, 3, 1),
        )
    return household


@pytest.fixture
def destination(other_household, other_user, source):
    """A fresh household, seeded only with the names the export lists.

    Seeding by name rather than by resolution is deliberate: it is what proves
    categorias.csv and formas_pagamento.csv actually carry what a re-import
    needs, rather than the test quietly supplying it.
    """
    archive = zipfile.ZipFile(io.BytesIO(build_export(source)))

    for row in csv_module.DictReader(
        io.StringIO(archive.read("categorias.csv").decode("utf-8-sig"))
    ):
        baker.make(Category, household=other_household, name=row["nome"])
    for row in csv_module.DictReader(
        io.StringIO(archive.read("formas_pagamento.csv").decode("utf-8-sig"))
    ):
        baker.make(
            PaymentMethod,
            household=other_household,
            name=row["nome"],
            type=row["tipo"],
            closing_day=int(row["dia_fechamento"] or 0) or None,
        )
    return other_household


@pytest.fixture
def destination_client(other_user):
    client = Client()
    client.force_login(other_user)
    return client


@pytest.mark.django_db
class TestRoundTrip:
    def _import_entries(self, client, household, archive_bytes):
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))

        handle = io.BytesIO(archive.read("entradas.csv"))
        handle.name = "entradas.csv"
        client.post("/import/", data={"file": handle, "import_type": "regular"})
        job = ImportJob.objects.for_household(household).latest("created_at")
        client.post(f"/import/{job.id}/mapear/", data=_MAPPING)
        client.post(f"/import/{job.id}/executar/")
        job.refresh_from_db()
        return job

    def test_the_ledger_total_matches(self, source, destination, destination_client):
        exported = build_export(source)
        job = self._import_entries(destination_client, destination, exported)

        assert job.error_count == 0, job.failures
        assert job.created_count == 4

        def total(household):
            return sum(Entry.objects.for_household(household).values_list("amount", flat=True))

        assert total(destination) == total(source)

    def test_the_per_category_split_matches(self, source, destination, destination_client):
        """A total that matches while the split does not is the failure mode
        this product exists to prevent."""
        self._import_entries(destination_client, destination, build_export(source))

        def by_category(household):
            result = {}
            for entry in Entry.objects.for_household(household).select_related("category"):
                name = entry.category.name
                result[name] = result.get(name, Decimal("0")) + entry.amount
            return result

        assert by_category(destination) == by_category(source)

    def test_the_utf8_bom_does_not_corrupt_the_first_column(
        self, source, destination, destination_client
    ):
        """The BOM makes Excel readable and would make the importer's first
        header unmatchable if it leaked into the header name. Caught here
        rather than by a user whose date column silently stopped mapping."""
        job = self._import_entries(destination_client, destination, build_export(source))
        assert job.column_mapping.get("date") == 0

    def test_a_second_import_of_the_same_export_is_flagged_duplicate(
        self, source, destination, destination_client
    ):
        """Idempotence across the round trip, not just within one run."""
        from finances.services.import_rows import rows_for

        exported = build_export(source)
        self._import_entries(destination_client, destination, exported)

        second = self._import_entries(destination_client, destination, exported)
        # The runner already ran; re-derive the preview's view of the file.
        assert {row["status"] for row in rows_for(second)} == {"duplicate"}

    def test_re_importing_the_same_export_changes_nothing(
        self, source, destination, destination_client
    ):
        """The consequence of the line above, stated as money rather than as
        row status: re-importing your own export does not double your ledger.

        And it holds **without the user ticking anything**. That is the point:
        the recovery this epic advertises after a failed or interrupted import
        is "send the file again", and a recovery that silently doubles the
        ledger unless the user notices 400 unchecked boxes is not a recovery.
        A review of the merged branch caught exactly that -- the preview badged
        the rows "Dup" and excluded them from "Importar N entradas →" while the
        runner created them anyway.
        """
        exported = build_export(source)
        self._import_entries(destination_client, destination, exported)
        before = Entry.objects.for_household(destination).count()
        assert before == 4

        second = self._import_entries(destination_client, destination, exported)

        assert Entry.objects.for_household(destination).count() == before
        assert second.created_count == 0
        assert second.skipped_count == 4
