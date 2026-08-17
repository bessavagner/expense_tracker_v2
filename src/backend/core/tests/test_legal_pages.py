"""The notice says what the code does — asserted, not hoped.

Most of this file is unusual for a test suite: it reads a rendered legal
document and checks its factual claims against the implementation. That is the
point. A privacy notice is the only document in this repository that is
simultaneously marketing copy, a legal instrument and a description of a
system, and only the third of those can be tested.

What is NOT tested here is whether the document is legally sufficient. That is
the DoD item no engineer can close.
"""

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from core.privacy import Basis, purgeable
from core.privacy.subprocessors import SUBPROCESSORS

pytestmark = pytest.mark.django_db


@pytest.fixture
def notice():
    return Client().get(reverse("privacy_notice")).content.decode()


@pytest.fixture
def terms():
    return Client().get(reverse("terms_of_service")).content.decode()


class TestBothDocumentsArePublic:
    def test_the_notice_needs_no_account(self):
        """Somebody deciding whether to sign up has to be able to read it."""
        response = Client().get(reverse("privacy_notice"))
        assert response.status_code == 200

    def test_the_terms_need_no_account(self):
        assert Client().get(reverse("terms_of_service")).status_code == 200

    def test_a_signed_in_user_mid_onboarding_is_not_redirected_away(self, user, new_household):
        """`onboarding_redirect_middleware` 302s every non-exempt GET for a
        household that has not finished setup — which is every new signup, and
        exactly the person most likely to click 'Aviso de Privacidade' on the
        form they are filling in."""
        client = Client()
        client.force_login(user)
        assert client.get(reverse("privacy_notice")).status_code == 200
        assert client.get(reverse("terms_of_service")).status_code == 200

    def test_both_are_reachable_from_the_public_footer(self):
        body = Client().get(reverse("account_login")).content.decode()
        assert reverse("privacy_notice") in body
        assert reverse("terms_of_service") in body


class TestTheControllerIsNamed:
    def test_the_controller_is_not_blank_in_this_environment(self, settings):
        """Guards the three tests below, which would otherwise pass vacuously:
        `"" in anything` is True."""
        for key in ("name", "cnpj", "address", "email"):
            assert settings.PRIVACY_CONTROLLER[key].strip(), (
                f"PRIVACY_CONTROLLER[{key!r}] is blank — set it in .env, and see "
                "core/checks_privacy.py"
            )

    def test_the_notice_names_the_controller(self, notice, settings):
        """LGPD art. 9 and art. 41: the notice must identify the controller and
        give a channel. A document that does neither is not a notice."""
        assert settings.PRIVACY_CONTROLLER["name"] in notice
        assert settings.PRIVACY_CONTROLLER["cnpj"] in notice

    def test_the_notice_gives_a_contact_for_privacy_questions(self, notice, settings):
        assert settings.PRIVACY_CONTROLLER["email"] in notice

    def test_it_says_what_the_deadline_is(self, notice):
        """15 days, LGPD art. 19. Printed where the person making the request
        can read it, not only in the runbook."""
        assert "15 dias" in notice

    def test_it_addresses_the_dpo_question_rather_than_ignoring_it(self, notice):
        assert "Encarregado" in notice


class TestEveryClaimAboutProcessing:
    def test_every_purpose_in_the_inventory_appears(self, notice):
        """Rendered from `core.privacy.INVENTORY`, so this cannot pass by
        accident — but it can fail loudly if someone hardcodes the table."""
        from core.privacy import INVENTORY, Disposal

        for record in INVENTORY:
            if record.disposal is Disposal.NONE:
                continue
            # First clause only: the notice wraps long purposes across cells.
            head = record.purpose.split(".")[0][:40]
            assert head in notice, f"{record.label}'s purpose is missing from the notice"

    def test_every_lawful_basis_is_cited_with_its_article(self, notice):
        for basis in Basis:
            assert basis.label in notice
            assert basis.article in notice

    def test_every_retention_period_appears(self, notice):
        for record in purgeable():
            if record.retention_days == 0:
                continue
            assert str(record.retention_days) in notice

    def test_it_says_content_goes_to_an_llm_provider_and_names_it(self, notice):
        """S13-4, and the single most important disclosure in the document."""
        assert "OpenAI" in notice

    def test_it_says_photos_and_audio_are_discarded(self, notice):
        """True today — `assistant/views.py` processes and drops them — and
        the one genuinely good privacy property this product already had."""
        assert "descartad" in notice

    def test_it_names_every_sub_processor(self, notice):
        for processor in SUBPROCESSORS:
            assert processor.name in notice

    def test_it_states_the_rights_lgpd_grants(self, notice):
        for right in ("acesso", "correção", "portabilidade", "exclusão", "anonimização"):
            assert right in notice.lower()

    def test_it_says_consent_for_the_ai_can_be_withdrawn_and_where(self, notice):
        assert "retirar" in notice.lower()
        assert reverse("account_privacy_tab") in notice


class TestTheClaimsMatchTheCode:
    def test_the_chat_period_it_prints_is_the_one_the_purge_uses(self, notice):
        from core.privacy import record_for

        assert str(record_for("assistant.ChatMessage").retention_days) in notice

    def test_it_does_not_promise_a_deletion_the_code_does_not_do(self, notice):
        """The notice must not claim the ledger is erased when a member leaves
        — plan decision D1 keeps it for the household, and saying otherwise
        would be a false statement about a system this test can read."""
        assert "continua com a casa" in notice or "permanece com a casa" in notice

    def test_it_carries_the_version_that_signup_records(self, notice):
        assert settings.PRIVACY_POLICY_VERSION in notice


class TestTheTerms:
    def test_they_carry_their_version(self, terms):
        assert settings.TERMS_VERSION in terms

    def test_they_describe_the_service(self, terms):
        assert "Ledger" in terms

    def test_they_cover_payment_even_though_nothing_is_charged_yet(self, terms):
        """S13-4 asks for terms 'covering the service, payment (forward-looking
        to E15), and termination'. Beta-is-free is a term, not the absence of
        one."""
        assert "grat" in terms.lower()

    def test_they_cover_termination_on_both_sides(self, terms):
        assert "encerrar" in terms.lower()

    def test_they_do_not_pretend_this_is_a_bank(self, terms):
        """The product is a bookkeeping tool. Any claim otherwise would be both
        false and regulated."""
        assert "não é" in terms and "instituição financeira" in terms


class TestTheControllerCannotShipBlank:
    def test_the_deploy_check_fails_when_the_controller_is_empty(self, settings):
        from django.core.checks import Error

        from core.checks_privacy import check_privacy_controller

        settings.PRIVACY_CONTROLLER = {"name": "", "cnpj": "", "address": "", "email": ""}
        problems = check_privacy_controller(None)

        assert problems
        assert isinstance(problems[0], Error)
        assert problems[0].id == "E13.001"

    def test_it_passes_when_the_controller_is_filled_in(self, settings):
        from core.checks_privacy import check_privacy_controller

        settings.PRIVACY_CONTROLLER = {
            "name": "Alguma Coisa LTDA",
            "cnpj": "00.000.000/0001-00",
            "address": "Rua Um, 1 — Fortaleza/CE",
            "email": "privacidade@exemplo.com",
        }
        assert check_privacy_controller(None) == []
