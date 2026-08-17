"""The assistant is the one part of this product that runs on consent.

Plan decision D3 puts chat, memory and receipt OCR on LGPD art. 7º, I. That is
only true if the answer to "no" is an actual refusal, and if refusing costs the
person nothing — no credits, no metering row, no record of an interaction they
did not have.
"""

import json

import pytest
from django.test import Client
from django.urls import reverse

from core.privacy import set_ai_consent

pytestmark = pytest.mark.django_db


def post_chat(client, message="oi"):
    return client.post(
        reverse("assistant:chat"),
        data=json.dumps({"message": message}),
        content_type="application/json",
    )


class TestTheGate:
    def test_without_consent_the_assistant_refuses(self, logged_client):
        response = post_chat(logged_client)
        assert response.status_code == 403

    def test_the_refusal_explains_itself_in_portuguese_and_says_where_to_fix_it(
        self, logged_client
    ):
        """The widget renders `error` as the assistant's reply, so this string
        is the user interface — not a log line."""
        body = post_chat(logged_client).json()
        assert "OpenAI" in body["error"]
        assert "Privacidade" in body["error"]

    def test_refusing_costs_nothing(self, logged_client, household):
        """No interaction, no usage row, no chat message. A refusal that still
        charged for itself would be worse than no gate at all."""
        from assistant.models import ChatMessage, UsageInteraction, UsageRecord

        post_chat(logged_client)

        assert not UsageInteraction.objects.filter(household=household).exists()
        assert not UsageRecord.objects.filter(household=household).exists()
        assert not ChatMessage.objects.filter(household=household).exists()

    def test_with_consent_the_gate_lets_the_request_through(self, logged_client, user):
        """Past the gate, not past everything — the reply itself needs a model,
        which the suite refuses to call. Anything other than 403 proves the gate
        opened, and that is what this test is about."""
        set_ai_consent(user, granted=True)
        response = post_chat(logged_client)
        assert response.status_code != 403

    def test_revoking_closes_it_again(self, logged_client, user):
        set_ai_consent(user, granted=True)
        set_ai_consent(user, granted=False)
        assert post_chat(logged_client).status_code == 403

    def test_an_unauthenticated_caller_still_gets_403_for_being_unauthenticated(self):
        """The order matters: authentication first, then consent. Reversing it
        would let a stranger probe whether an account exists."""
        response = post_chat(Client())
        assert response.status_code == 403


class TestWhatIsNotGated:
    def test_reading_your_own_history_is_not_gated(self, logged_client, user):
        """History is the access right (S13-2). Refusing someone their own data
        because they withdrew consent to *future* processing would be the
        opposite of what consent is for."""
        set_ai_consent(user, granted=False)
        response = logged_client.get(reverse("assistant:history"))
        assert response.status_code == 200

    def test_the_ledger_still_works_without_consent(self, logged_client):
        """Contract, not consent (D3). If withdrawing consent broke the
        bookkeeping, the notice's claim that the product works without the
        assistant would be false."""
        response = logged_client.get("/")
        assert response.status_code == 200
