"""What is in the archive, and what is deliberately not."""

import csv
import io
import json
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.services.export_builder import (
    ARCHIVE_MEMBERS,
    build_export,
    format_amount,
    format_date,
)


@pytest.fixture
def populated(household, user):
    category = baker.make("finances.Category", household=household, name="Alimentação")
    payment = baker.make(
        "finances.PaymentMethod",
        household=household,
        name="Crédito C6",
        type="credit_card",
        closing_day=25,
    )
    baker.make(
        "finances.Entry",
        household=household,
        created_by=user,
        date=date(2026, 3, 1),
        amount=Decimal("1234.56"),
        description="Mercado",
        category=category,
        payment_method=payment,
        entry_type="regular",
        billing_month=date(2026, 4, 1),
    )
    baker.make(
        "finances.Income",
        household=household,
        name="Salário",
        amount=Decimal("5000.00"),
        month=date(2026, 3, 1),
    )
    baker.make(
        "assistant.ChatMessage",
        household=household,
        created_by=user,
        role="user",
        content="quanto gastei em março?",
    )
    return household


class TestFormatting:
    def test_amounts_are_ptbr_and_re_parseable(self):
        from finances.services.csv_parser import parse_amount

        assert format_amount(Decimal("1234.56")) == "1234,56"
        assert parse_amount(format_amount(Decimal("1234.56"))) == Decimal("1234.56")

    def test_negative_amounts_survive_the_round_trip(self):
        from finances.services.csv_parser import parse_amount

        assert parse_amount(format_amount(Decimal("-226.21"))) == Decimal("-226.21")

    def test_dates_are_ddmmyyyy_and_re_parseable(self):
        from finances.services.csv_parser import parse_date

        assert format_date(date(2026, 3, 1)) == "01/03/2026"
        assert parse_date(format_date(date(2026, 3, 1))) == date(2026, 3, 1)


@pytest.mark.django_db
class TestArchiveContents:
    def test_every_declared_member_is_present(self, populated):
        archive = zipfile.ZipFile(io.BytesIO(build_export(populated)))
        assert set(archive.namelist()) == set(ARCHIVE_MEMBERS)

    def test_entries_csv_uses_the_importers_own_headers(self, populated):
        archive = zipfile.ZipFile(io.BytesIO(build_export(populated)))
        text = archive.read("entradas.csv").decode("utf-8-sig")
        header = next(csv.reader(io.StringIO(text)))
        assert header == ["data", "valor", "descrição", "categoria", "forma"]

    def test_an_entry_appears_with_its_real_values(self, populated):
        archive = zipfile.ZipFile(io.BytesIO(build_export(populated)))
        text = archive.read("entradas.csv").decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        assert rows[0]["data"] == "01/03/2026"
        assert rows[0]["valor"] == "1234,56"
        assert rows[0]["descrição"] == "Mercado"
        assert rows[0]["categoria"] == "Alimentação"
        assert rows[0]["forma"] == "Crédito C6"

    def test_chat_history_is_in_the_json_and_not_in_any_csv(self, populated):
        """E12 decision 3. Portability covers the chat, so it ships -- but a
        leaked link to entradas.csv must not also be a transcript."""
        archive = zipfile.ZipFile(io.BytesIO(build_export(populated)))
        payload = json.loads(archive.read("ledger.json"))
        assert any("quanto gastei" in message["conteudo"] for message in payload["conversas"])
        for name in ARCHIVE_MEMBERS:
            if name.endswith(".csv"):
                assert "quanto gastei" not in archive.read(name).decode("utf-8-sig")

    def test_the_json_covers_every_model_the_spec_names(self, populated):
        archive = zipfile.ZipFile(io.BytesIO(build_export(populated)))
        payload = json.loads(archive.read("ledger.json"))
        assert set(payload) >= {
            "entradas",
            "receitas",
            "categorias",
            "formas_pagamento",
            "orcamentos",
            "parcelamentos",
            "despesas_sistemicas",
            "regras_memoria",
            "conversas",
            "rascunhos_recibo",
            "fechamentos",
            "importacoes",
            "meta",
        }

    def test_amounts_in_the_json_are_strings_not_floats(self, populated):
        """R$ 0,10 as a float is 0.1000000000000000055. This file is a
        financial record, so every amount stays exact."""
        archive = zipfile.ZipFile(io.BytesIO(build_export(populated)))
        payload = json.loads(archive.read("ledger.json"))
        assert payload["entradas"][0]["valor"] == "1234.56"

    def test_it_carries_a_ptbr_readme(self, populated):
        archive = zipfile.ZipFile(io.BytesIO(build_export(populated)))
        readme = archive.read("LEIA-ME.txt").decode()
        assert "entradas.csv" in readme
        assert "ledger.json" in readme


@pytest.mark.django_db
class TestInstallmentsAreNotDoubled:
    def test_entradas_csv_omits_installment_derived_entries(self, household, user):
        """They are regenerated from parcelamentos.csv on re-import. Shipping
        both would double every parcelled purchase, and the user's re-import
        would not notice."""
        category = baker.make("finances.Category", household=household, name="Roupa")
        payment = baker.make(
            "finances.PaymentMethod",
            household=household,
            name="Crédito C6",
            type="credit_card",
            closing_day=25,
        )
        plan = baker.make(
            "finances.InstallmentPlan",
            household=household,
            created_by=user,
            date=date(2026, 3, 1),
            description="Camisetas",
            category=category,
            payment_method=payment,
            total_amount=Decimal("200.00"),
            num_installments=2,
            installment_amount=Decimal("100.00"),
        )
        plan.generate_entries()

        archive = zipfile.ZipFile(io.BytesIO(build_export(household)))
        entries_csv = archive.read("entradas.csv").decode("utf-8-sig")
        plans_csv = archive.read("parcelamentos.csv").decode("utf-8-sig")

        assert "Camisetas" not in entries_csv
        assert "Camisetas" in plans_csv
        # ...but the derived entries are still in the JSON, which is a complete
        # record rather than a re-importable one. generate_entries() names them
        # "Camisetas (1/2)", "Camisetas (2/2)".
        payload = json.loads(archive.read("ledger.json"))
        derived = [
            entry for entry in payload["entradas"] if entry["descricao"].startswith("Camisetas")
        ]
        assert len(derived) == 2
        assert all(entry["parcelamento"] == str(plan.id) for entry in derived)


@pytest.mark.django_db
class TestTenancy:
    def test_it_exports_only_the_named_household(self, populated, other_household):
        baker.make(
            "finances.Entry",
            household=other_household,
            description="ALHEIO",
            amount=Decimal("1.00"),
            date=date(2026, 3, 1),
            billing_month=date(2026, 3, 1),
        )
        archive = zipfile.ZipFile(io.BytesIO(build_export(populated)))
        for name in archive.namelist():
            assert b"ALHEIO" not in archive.read(name)

    def test_an_empty_household_still_produces_a_valid_archive(self, household):
        archive = zipfile.ZipFile(io.BytesIO(build_export(household)))
        assert set(archive.namelist()) == set(ARCHIVE_MEMBERS)
