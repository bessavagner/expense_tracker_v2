"""Consent for the AI leg, and the record that a policy version was accepted.

The assistant runs on consent (plan decision D3), which is only true if it can
be withheld and taken back. These tests are what stops that becoming a sentence
in a document with no code behind it.
"""

from datetime import UTC, datetime

import pytest
from django.conf import settings
from django.db import IntegrityError
from model_bakery import baker

from core.models import Consent, ConsentPurpose, PolicyAcceptance, PolicyDocument
from core.privacy.consent import has_ai_consent, set_ai_consent

pytestmark = pytest.mark.django_db

FROZEN_NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


class TestAIConsent:
    def test_a_new_account_has_not_consented(self):
        """Absence is a refusal. Defaulting to granted would make the whole
        mechanism decorative."""
        person = baker.make("core.CustomUser", email="nova@example.com")
        assert has_ai_consent(person) is False

    def test_granting_it_is_recorded_with_the_moment_it_happened(self, time_machine):
        time_machine.move_to(FROZEN_NOW, tick=False)
        person = baker.make("core.CustomUser", email="vagner@example.com")

        consent = set_ai_consent(person, granted=True)

        assert has_ai_consent(person) is True
        assert consent.granted is True
        assert consent.granted_at == FROZEN_NOW
        assert consent.revoked_at is None

    def test_revoking_it_keeps_the_row_and_stamps_the_revocation(self, time_machine):
        """The row is not deleted: 'they consented on the 17th and withdrew on
        the 20th' is the evidence an ANPD question asks for, and a deleted row
        cannot answer it."""
        time_machine.move_to(FROZEN_NOW, tick=False)
        person = baker.make("core.CustomUser", email="vagner@example.com")
        set_ai_consent(person, granted=True)

        time_machine.move_to(datetime(2026, 8, 20, 12, 0, tzinfo=UTC), tick=False)
        consent = set_ai_consent(person, granted=False)

        assert has_ai_consent(person) is False
        assert consent.granted is False
        assert consent.granted_at == FROZEN_NOW
        assert consent.revoked_at == datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

    def test_granting_again_after_a_revocation_clears_the_revocation(self, time_machine):
        time_machine.move_to(FROZEN_NOW, tick=False)
        person = baker.make("core.CustomUser", email="vagner@example.com")
        set_ai_consent(person, granted=True)
        set_ai_consent(person, granted=False)

        consent = set_ai_consent(person, granted=True)

        assert has_ai_consent(person) is True
        assert consent.revoked_at is None

    def test_one_row_per_person_per_purpose(self):
        person = baker.make("core.CustomUser", email="vagner@example.com")
        set_ai_consent(person, granted=True)
        set_ai_consent(person, granted=False)
        set_ai_consent(person, granted=True)

        assert Consent.objects.filter(user=person).count() == 1

    def test_the_database_refuses_a_second_row_for_the_same_purpose(self):
        person = baker.make("core.CustomUser", email="vagner@example.com")
        Consent.objects.create(user=person, purpose=ConsentPurpose.AI_ASSISTANT, granted=True)
        with pytest.raises(IntegrityError):
            Consent.objects.create(user=person, purpose=ConsentPurpose.AI_ASSISTANT, granted=True)

    def test_one_persons_consent_is_not_anothers(self):
        alice = baker.make("core.CustomUser", email="alice@example.com")
        bruno = baker.make("core.CustomUser", email="bruno@example.com")
        set_ai_consent(alice, granted=True)
        assert has_ai_consent(bruno) is False

    def test_an_anonymous_visitor_has_not_consented(self):
        """`has_ai_consent` is called from a view that has already checked
        authentication, but a permission helper that raises on absent input
        becomes a 500 on the exact request that should have been a 403 — the
        same rule `accounts.permissions.is_owner` follows."""
        from django.contrib.auth.models import AnonymousUser

        assert has_ai_consent(AnonymousUser()) is False
        assert has_ai_consent(None) is False


class TestPolicyAcceptance:
    def test_an_acceptance_records_the_document_the_version_and_the_moment(self, time_machine):
        time_machine.move_to(FROZEN_NOW, tick=False)
        person = baker.make("core.CustomUser", email="vagner@example.com")

        acceptance = PolicyAcceptance.objects.create(
            user=person,
            document=PolicyDocument.PRIVACY,
            version=settings.PRIVACY_POLICY_VERSION,
            ip="203.0.113.7",
        )

        assert acceptance.accepted_at == FROZEN_NOW
        assert acceptance.version == settings.PRIVACY_POLICY_VERSION

    def test_the_same_version_cannot_be_accepted_twice(self):
        """Idempotence at the database, so a double-submitted signup form
        cannot write two rows and make 'when did they accept?' ambiguous."""
        person = baker.make("core.CustomUser", email="vagner@example.com")
        PolicyAcceptance.objects.create(
            user=person, document=PolicyDocument.TERMS, version="2026-08-17"
        )
        with pytest.raises(IntegrityError):
            PolicyAcceptance.objects.create(
                user=person, document=PolicyDocument.TERMS, version="2026-08-17"
            )

    def test_a_new_version_is_a_new_row_rather_than_an_update(self):
        person = baker.make("core.CustomUser", email="vagner@example.com")
        PolicyAcceptance.objects.create(
            user=person, document=PolicyDocument.TERMS, version="2026-08-17"
        )
        PolicyAcceptance.objects.create(
            user=person, document=PolicyDocument.TERMS, version="2027-01-04"
        )
        assert PolicyAcceptance.objects.filter(user=person).count() == 2


class TestTheVersionsAreConfigured:
    def test_both_documents_carry_a_version(self):
        """Blank versions would record an acceptance of nothing in particular."""
        assert settings.PRIVACY_POLICY_VERSION.strip()
        assert settings.TERMS_VERSION.strip()

    def test_the_versions_are_dates_so_a_human_can_order_them(self):
        from datetime import date

        date.fromisoformat(settings.PRIVACY_POLICY_VERSION)
        date.fromisoformat(settings.TERMS_VERSION)
