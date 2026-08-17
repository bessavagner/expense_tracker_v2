"""Privacidade: see it, correct it, take it with you.

S13-2. The access right is not "we would send it if you emailed us" — it is a
page. The correction right is not "we would change it" — it is a button. This
suite is what makes those two sentences true.
"""

import pytest
from django.test import Client
from django.urls import reverse

from assistant.models import MemoryRule, MemorySource
from core.privacy import has_ai_consent, set_ai_consent

pytestmark = pytest.mark.django_db


@pytest.fixture
def rule(household, user):
    return MemoryRule.objects.create(
        household=household,
        created_by=user,
        trigger="cosmos",
        field="category",
        value="Alimentação",
        source=MemorySource.INFERRED,
    )


class TestTheTab:
    def test_it_requires_login(self):
        response = Client().get(reverse("account_privacy_tab"))
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    def test_the_fragment_url_renders_standalone(self, logged_client, household):
        response = logged_client.get(reverse("account_privacy_tab"))
        assert response.status_code == 200
        assert "<!DOCTYPE html>" in response.content.decode()

    def test_as_an_htmx_fragment_it_is_not_a_whole_page(self, logged_client, household):
        response = logged_client.get(reverse("account_privacy_tab"), headers={"HX-Request": "true"})
        assert "<!DOCTYPE html>" not in response.content.decode()

    def test_the_conta_page_offers_it_as_a_tab(self, logged_client, household):
        body = logged_client.get(reverse("account")).content.decode()
        assert reverse("account_privacy_tab") in body
        assert "Privacidade" in body


class TestPortability:
    def test_it_sends_you_to_the_export_rather_than_reinventing_one(self, logged_client, household):
        """E12 already built this. E13 consumes it — the epic says so in as
        many words, and a second export path is a second thing to keep correct."""
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert reverse("finances:export_page") in body


class TestWhatTheAssistantThinksItKnows:
    def test_the_inferred_rules_are_shown(self, logged_client, household, rule):
        """The epic's own words: users have a right to see these and are likely
        to find them surprising."""
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert "cosmos" in body
        assert "Alimentação" in body

    def test_a_neighbours_rules_are_not_shown(
        self, logged_client, household, other_household, other_user
    ):
        MemoryRule.objects.create(
            household=other_household,
            created_by=other_user,
            trigger="segredo-da-vizinha",
            field="category",
            value="Outros",
            source=MemorySource.INFERRED,
        )
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert "segredo-da-vizinha" not in body

    def test_a_rule_can_be_deleted_which_is_the_correction_right(
        self, logged_client, household, rule
    ):
        response = logged_client.post(
            reverse("account_memory_rule_delete", args=[rule.pk]),
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert not MemoryRule.objects.filter(pk=rule.pk).exists()

    def test_deleting_a_rule_takes_its_embedding_with_it(self, logged_client, household, rule):
        """Otherwise the vector of that inference survives the correction, and
        semantic lookup keeps finding a rule the person deleted."""
        from assistant.models import MemoryEmbedding
        from assistant.tasks import embedding_id_for

        MemoryEmbedding.objects.create(
            id=embedding_id_for(rule.pk),
            household=household,
            text="cosmos → category=Alimentação",
            embedding=[0.0] * 1536,
        )

        logged_client.post(
            reverse("account_memory_rule_delete", args=[rule.pk]),
            headers={"HX-Request": "true"},
        )

        assert not MemoryEmbedding.objects.filter(id=embedding_id_for(rule.pk)).exists()

    def test_a_neighbours_rule_cannot_be_deleted(
        self, logged_client, household, other_household, other_user
    ):
        """404, not 403: whether a row exists in another household is itself
        something this endpoint must not disclose."""
        theirs = MemoryRule.objects.create(
            household=other_household,
            created_by=other_user,
            trigger="cosmos",
            field="category",
            value="Outros",
            source=MemorySource.INFERRED,
        )
        response = logged_client.post(
            reverse("account_memory_rule_delete", args=[theirs.pk]),
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 404
        assert MemoryRule.objects.filter(pk=theirs.pk).exists()

    def test_a_get_cannot_delete_a_rule(self, logged_client, household, rule):
        """A GET that destroys something is a URL an email scanner follows."""
        response = logged_client.get(reverse("account_memory_rule_delete", args=[rule.pk]))
        assert response.status_code == 405
        assert MemoryRule.objects.filter(pk=rule.pk).exists()


class TestTheConsentToggle:
    def test_it_shows_consent_as_absent_for_a_new_account(self, logged_client, household):
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert "Não autorizado" in body

    def test_granting_it_from_here_works(self, logged_client, household, user):
        response = logged_client.post(
            reverse("account_ai_consent"),
            {"granted": "1"},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert has_ai_consent(user) is True
        assert "Autorizado" in response.content.decode()

    def test_revoking_it_from_here_works(self, logged_client, household, user):
        set_ai_consent(user, granted=True)
        response = logged_client.post(
            reverse("account_ai_consent"),
            {"granted": "0"},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert has_ai_consent(user) is False

    def test_it_cannot_be_used_to_consent_on_somebody_elses_behalf(
        self, logged_client, household, other_user
    ):
        """The view reads `request.user` and takes no id. This asserts that
        stays true if anyone ever adds one."""
        logged_client.post(
            reverse("account_ai_consent"),
            {"granted": "1", "user": other_user.pk, "id": other_user.pk},
            headers={"HX-Request": "true"},
        )
        assert has_ai_consent(other_user) is False


class TestWhatItTellsYou:
    def test_it_states_the_chat_retention_period(self, logged_client, household):
        """Rendered from the inventory, so it cannot drift from what the purge
        job actually does."""
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert "90" in body

    def test_it_links_the_notice_and_the_terms(self, logged_client, household):
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert reverse("privacy_notice") in body
        assert reverse("terms_of_service") in body

    def test_it_shows_which_version_you_accepted(self, logged_client, household, user):
        from core.models import PolicyAcceptance, PolicyDocument

        PolicyAcceptance.objects.create(
            user=user, document=PolicyDocument.PRIVACY, version="2026-08-17"
        )
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert "2026-08-17" in body

    def test_it_offers_the_way_out(self, logged_client, household):
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert reverse("account_delete") in body
