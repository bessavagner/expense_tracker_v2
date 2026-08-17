"""The archive is the access right, so it has to actually be complete.

E12 built the machinery and E13 consumes it — but two models say in their own
docstrings that E13 exports them, and until this task neither was in the file.
The test that matters here is the last one: it walks the inventory rather than
a list, so a model that starts holding personal data next year cannot quietly
stay out of the export.
"""

import io
import json
import zipfile

import pytest
from model_bakery import baker

from finances.services.export_builder import build_export

pytestmark = pytest.mark.django_db


def ledger(household) -> dict:
    archive = zipfile.ZipFile(io.BytesIO(build_export(household)))
    return json.loads(archive.read("ledger.json"))


class TestTheAccountItself:
    def test_the_address_and_the_name_are_in_it(self, household, user):
        user.first_name = "Vagner"
        user.save(update_fields=["first_name"])

        conta = ledger(household)["conta"]

        assert any(pessoa["email"] == "vagner@example.com" for pessoa in conta["pessoas"])
        assert any(pessoa["nome"] == "Vagner" for pessoa in conta["pessoas"])

    def test_the_household_and_the_role_are_in_it(self, household, user):
        conta = ledger(household)["conta"]
        assert conta["casa"]["nome"] == household.name
        assert conta["pessoas"][0]["papel"] == "owner"

    def test_the_accepted_policy_versions_are_in_it(self, household, user):
        from core.models import PolicyAcceptance, PolicyDocument

        PolicyAcceptance.objects.create(
            user=user, document=PolicyDocument.PRIVACY, version="2026-08-17"
        )

        aceites = ledger(household)["conta"]["aceites"]

        assert {"documento": "privacy", "versao": "2026-08-17"} in [
            {"documento": a["documento"], "versao": a["versao"]} for a in aceites
        ]

    def test_the_ai_consent_state_is_in_it(self, household, user):
        from core.privacy import set_ai_consent

        set_ai_consent(user, granted=True)

        consentimentos = ledger(household)["conta"]["consentimentos"]

        assert consentimentos[0]["finalidade"] == "ai_assistant"
        assert consentimentos[0]["concedido"] is True

    def test_no_password_hash_leaves_the_building(self, household, user):
        """An export is a file people email to themselves. A password hash in
        it is a credential in an inbox."""
        raw = json.dumps(ledger(household))
        assert user.password not in raw
        assert "pbkdf2" not in raw


class TestProductEvents:
    def test_they_are_exported(self, household, user):
        """`core.models.ProductEvent`'s own docstring says 'exported by E13'."""
        from core.events import EventName
        from core.models import ProductEvent

        ProductEvent.objects.create(
            household=household, user=user, name=EventName.ACTIVATED, once=True
        )

        eventos = ledger(household)["eventos"]

        assert any(evento["nome"] == "activated" for evento in eventos)

    def test_a_neighbours_events_are_not(self, household, other_household, other_user):
        from core.events import EventName
        from core.models import ProductEvent

        ProductEvent.objects.create(
            household=other_household, user=other_user, name=EventName.SIGNUP
        )

        assert ledger(household)["eventos"] == []


class TestFeedback:
    def test_it_is_exported(self, household, user):
        from core.models import Feedback

        Feedback.objects.create(household=household, user=user, message="tá lento")

        feedbacks = ledger(household)["feedbacks"]

        assert feedbacks[0]["mensagem"] == "tá lento"

    def test_a_neighbours_feedback_is_not(self, household, other_household, other_user):
        from core.models import Feedback

        Feedback.objects.create(household=other_household, user=other_user, message="segredo")

        assert ledger(household)["feedbacks"] == []


class TestUsage:
    def test_what_the_ai_cost_is_exported(self, household, user):
        from assistant.models import InteractionKind, UsageInteraction

        baker.make(
            UsageInteraction,
            household=household,
            user=user,
            kind=InteractionKind.TEXT,
            credits_charged=3,
        )

        uso = ledger(household)["uso"]

        assert uso[0]["creditos"] == 3
        assert uso[0]["tipo"] == "text"


class TestTheArchiveIsStillWhatE12Built:
    def test_the_same_files_are_in_it(self, household):
        from finances.services.export_builder import ARCHIVE_MEMBERS

        archive = zipfile.ZipFile(io.BytesIO(build_export(household)))
        assert set(archive.namelist()) == set(ARCHIVE_MEMBERS)

    def test_the_chat_and_the_memory_rules_are_still_there(self, household, user):
        """E12 decision 3. Regression guard: this task edits the same dict."""
        from assistant.models import ChatMessage, MessageRole

        ChatMessage.objects.create(
            household=household, created_by=user, role=MessageRole.USER, content="oi"
        )

        payload = ledger(household)

        assert payload["conversas"][0]["conteudo"] == "oi"
        assert "regras_memoria" in payload

    def test_the_format_number_went_up(self, household):
        assert ledger(household)["meta"]["formato"] == 2

    def test_the_readme_mentions_what_was_added(self, household):
        archive = zipfile.ZipFile(io.BytesIO(build_export(household)))
        readme = archive.read("LEIA-ME.txt").decode()
        assert "conta" in readme.lower()


class TestTheContaSectionIsScopedToThisHousehold:
    """The `conta` section joins through `user__memberships__household`, which is
    the one query in this file that reaches *people* rather than rows. E13's plan
    flagged it for security review by name, so the answer lives here as a test
    rather than in a reviewer's memory."""

    def test_a_member_of_two_households_does_not_bleed_between_them(
        self, household, user, other_household, other_user
    ):
        """`user` is in BOTH households; `other_user` is only in the second.
        The first household's archive must not name the second's member."""
        from accounts.models import Membership, Role
        from core.models import PolicyAcceptance, PolicyDocument
        from core.privacy import set_ai_consent

        Membership.objects.create(user=user, household=other_household, role=Role.MEMBER)
        PolicyAcceptance.objects.create(
            user=user, document=PolicyDocument.TERMS, version="2026-08-17"
        )
        PolicyAcceptance.objects.create(
            user=other_user, document=PolicyDocument.TERMS, version="2026-08-17"
        )
        set_ai_consent(user, granted=True)
        set_ai_consent(other_user, granted=True)

        raw = json.dumps(ledger(household), ensure_ascii=False)

        assert other_user.email not in raw

    def test_the_membership_join_does_not_multiply_rows(self, household, user, other_household):
        """A person in two households matches the join once per household. The
        filter pins one, so an acceptance is listed once rather than squared."""
        from accounts.models import Membership, Role
        from core.models import PolicyAcceptance, PolicyDocument

        Membership.objects.create(user=user, household=other_household, role=Role.MEMBER)
        PolicyAcceptance.objects.create(
            user=user, document=PolicyDocument.TERMS, version="2026-08-17"
        )

        assert len(ledger(household)["conta"]["aceites"]) == 1


class TestNothingPersonalIsLeftOut:
    def test_every_household_owned_model_holding_personal_data_is_in_the_archive(self, household):
        """The completeness assertion, driven by the inventory rather than by a
        list here — so a model that starts holding personal data next year
        cannot quietly stay out of an access request.

        The mapping is explicit because a `ledger.json` key is a pt-BR word
        chosen for a person reading the file, not a model label. Adding a
        household-owned model with a lawful basis means adding a line here and
        a section to the builder, and the test says which.
        """
        from accounts.models import household_owned_models
        from core.privacy import Disposal, record_for

        exported_under = {
            "finances.Entry": "entradas",
            "finances.InstallmentPlan": "parcelamentos",
            "finances.Income": "receitas",
            "finances.Category": "categorias",
            "finances.PaymentMethod": "formas_pagamento",
            "finances.Budget": "orcamentos",
            "finances.SystemicExpense": "despesas_sistemicas",
            "finances.ImportJob": "importacoes",
            "finances.ExportJob": "exportacoes",
            "assistant.ChatMessage": "conversas",
            "assistant.MemoryRule": "regras_memoria",
            "assistant.MemoryEmbedding": "regras_memoria",
            "assistant.ReceiptDraft": "rascunhos_recibo",
            "assistant.UsageInteraction": "uso",
            "assistant.UsageRecord": "uso",
            "core.ProductEvent": "eventos",
            "core.Feedback": "feedbacks",
            "accounts.Invitation": "conta",
        }

        payload = ledger(household)
        missing = []
        for model in household_owned_models():
            record = record_for(model._meta.label)
            if record.disposal is Disposal.NONE:
                continue
            key = exported_under.get(model._meta.label)
            if key is None or key not in payload:
                missing.append(model._meta.label)

        assert not missing, (
            "these hold personal data and are not in the export — add a section "
            f"to export_builder.build_export and a line to this map: {missing}"
        )
