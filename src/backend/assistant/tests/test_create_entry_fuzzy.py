"""Tests for lenient name resolution in create_entry (fix: inferência fraca).

Root cause: o usuário escreve "c6" mas a tool fazia match EXATO
(PaymentMethod.objects.get(name=...)), então "c6" != "Crédito C6" falhava
e o agente pedia desambiguação desnecessária. Agora a tool resolve por
correspondência case-insensitive / parcial quando não-ambígua.
"""

import pytest
from model_bakery import baker

from assistant.agents.tools import create_entry
from finances.models import Entry


@pytest.mark.django_db
class TestCreateEntryFuzzyPayment:
    def test_partial_lowercase_resolves(self, seeded_user, seeded_scope, household):
        result = create_entry(
            seeded_scope,
            date_str="2026-06-12",
            amount_str="30.00",
            description="Sabor da Família",
            category_name="Alimentação",
            payment_method_name="c6",
        )
        assert "criada" in result.lower() or "registrada" in result.lower()
        entry = Entry.objects.for_household(household).get(description="Sabor da Família")
        assert entry.payment_method.name == "Crédito C6"

    def test_exact_name_still_works(self, seeded_user, seeded_scope, household):
        create_entry(
            seeded_scope,
            date_str="2026-06-12",
            amount_str="30.00",
            description="Exata",
            category_name="Alimentação",
            payment_method_name="Crédito C6",
        )
        entry = Entry.objects.for_household(household).get(description="Exata")
        assert entry.payment_method.name == "Crédito C6"

    def test_ambiguous_partial_returns_options_without_writing(
        self, seeded_user, seeded_scope, household
    ):
        baker.make(
            "finances.PaymentMethod",
            household=household,
            name="Crédito C6 Adicional",
            type="credit_card",
            closing_day=25,
        )
        result = create_entry(
            seeded_scope,
            date_str="2026-06-12",
            amount_str="30.00",
            description="Ambígua",
            category_name="Alimentação",
            payment_method_name="c6",
        )
        assert "erro" in result.lower() or "ambíg" in result.lower()
        # nada deve ser gravado quando ambíguo
        assert not Entry.objects.for_household(household).filter(description="Ambígua").exists()

    def test_unknown_payment_still_errors(self, seeded_user, seeded_scope, household):
        result = create_entry(
            seeded_scope,
            date_str="2026-06-12",
            amount_str="30.00",
            description="Desconhecida",
            category_name="Alimentação",
            payment_method_name="cartão inexistente",
        )
        assert "erro" in result.lower() or "não encontrada" in result.lower()
        assert (
            not Entry.objects.for_household(household).filter(description="Desconhecida").exists()
        )


@pytest.mark.django_db
class TestCreateEntryCategoryCaseInsensitive:
    def test_lowercase_category_resolves(self, seeded_user, seeded_scope, household):
        result = create_entry(
            seeded_scope,
            date_str="2026-06-12",
            amount_str="30.00",
            description="Cat minúscula",
            category_name="alimentação",
            payment_method_name="Pix",
        )
        assert "criada" in result.lower() or "registrada" in result.lower()
        entry = Entry.objects.for_household(household).get(description="Cat minúscula")
        assert entry.category.name == "Alimentação"


@pytest.mark.django_db
class TestNameResolutionIsAccentInsensitive:
    """D02: the resolver was case-insensitive but accent-SENSITIVE.

    A live run on gpt-5.4 (2026-08-15) failed a behavioural case exactly here:
    the user wrote "Credito C6", the model wrote "Crédito C6" — correct
    Portuguese — and the tool refused a payment method its own error message
    then listed. The same wall meets a user typing "alimentacao" on a phone
    keyboard against a category stored as "Alimentação".
    """

    def test_an_accented_name_resolves_an_unaccented_row(
        self, seeded_user, seeded_scope, household
    ):
        baker.make(
            "finances.PaymentMethod",
            household=household,
            name="Credito C6 Sem Acento",
            type="credit_card",
            closing_day=25,
        )

        result = create_entry(
            seeded_scope,
            date_str="2026-06-12",
            amount_str="30.00",
            description="Acentuada",
            category_name="Alimentação",
            payment_method_name="Crédito C6 Sem Acento",
        )

        assert "não encontrada" not in result, result
        entry = Entry.objects.for_household(household).get(description="Acentuada")
        assert entry.payment_method.name == "Credito C6 Sem Acento"

    def test_an_unaccented_name_resolves_an_accented_row(
        self, seeded_user, seeded_scope, household
    ):
        """The phone-keyboard direction: no accents typed, accents stored."""
        create_entry(
            seeded_scope,
            date_str="2026-06-12",
            amount_str="30.00",
            description="Sem acento",
            category_name="Alimentacao",
            payment_method_name="Credito C6",
        )

        entry = Entry.objects.for_household(household).get(description="Sem acento")
        assert entry.category.name == "Alimentação"
        assert entry.payment_method.name == "Crédito C6"

    def test_the_ambiguity_message_still_names_the_stored_spelling(
        self, seeded_user, seeded_scope, household
    ):
        """Folding is for MATCHING. What we show the user is what they stored."""
        baker.make(
            "finances.PaymentMethod",
            household=household,
            name="Crédito C6 Adicional",
            type="credit_card",
            closing_day=25,
        )

        result = create_entry(
            seeded_scope,
            date_str="2026-06-12",
            amount_str="30.00",
            description="Ambigua sem acento",
            category_name="Alimentacao",
            # Unaccented AND partial, so it cannot resolve exactly: it matches
            # both stored methods and has to ask.
            payment_method_name="credito c",
        )

        assert "ambígua" in result.lower()
        assert "Crédito C6" in result
        assert (
            not Entry.objects.for_household(household)
            .filter(description="Ambigua sem acento")
            .exists()
        )
