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
    def test_partial_lowercase_resolves(self, seeded_user):
        result = create_entry(
            user=seeded_user,
            date_str="2026-06-12",
            amount_str="30.00",
            description="Sabor da Família",
            category_name="Alimentação",
            payment_method_name="c6",
        )
        assert "criada" in result.lower() or "registrada" in result.lower()
        entry = Entry.objects.get(user=seeded_user, description="Sabor da Família")
        assert entry.payment_method.name == "Crédito C6"

    def test_exact_name_still_works(self, seeded_user):
        create_entry(
            user=seeded_user,
            date_str="2026-06-12",
            amount_str="30.00",
            description="Exata",
            category_name="Alimentação",
            payment_method_name="Crédito C6",
        )
        entry = Entry.objects.get(user=seeded_user, description="Exata")
        assert entry.payment_method.name == "Crédito C6"

    def test_ambiguous_partial_returns_options_without_writing(self, seeded_user):
        baker.make(
            "finances.PaymentMethod",
            user=seeded_user,
            name="Crédito C6 Adicional",
            type="credit_card",
            closing_day=25,
        )
        result = create_entry(
            user=seeded_user,
            date_str="2026-06-12",
            amount_str="30.00",
            description="Ambígua",
            category_name="Alimentação",
            payment_method_name="c6",
        )
        assert "erro" in result.lower() or "ambíg" in result.lower()
        # nada deve ser gravado quando ambíguo
        assert not Entry.objects.filter(user=seeded_user, description="Ambígua").exists()

    def test_unknown_payment_still_errors(self, seeded_user):
        result = create_entry(
            user=seeded_user,
            date_str="2026-06-12",
            amount_str="30.00",
            description="Desconhecida",
            category_name="Alimentação",
            payment_method_name="cartão inexistente",
        )
        assert "erro" in result.lower() or "não encontrada" in result.lower()
        assert not Entry.objects.filter(user=seeded_user, description="Desconhecida").exists()


@pytest.mark.django_db
class TestCreateEntryCategoryCaseInsensitive:
    def test_lowercase_category_resolves(self, seeded_user):
        result = create_entry(
            user=seeded_user,
            date_str="2026-06-12",
            amount_str="30.00",
            description="Cat minúscula",
            category_name="alimentação",
            payment_method_name="Pix",
        )
        assert "criada" in result.lower() or "registrada" in result.lower()
        entry = Entry.objects.get(user=seeded_user, description="Cat minúscula")
        assert entry.category.name == "Alimentação"
