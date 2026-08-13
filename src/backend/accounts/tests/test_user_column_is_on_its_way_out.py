"""`user` is nullable on the twelve models that lose it in Task 13.

A three-beat schema dance: nullable here, every write site converted, then the
column dropped. This test pins beat one so that beat two can rewrite ~612 test
call sites in a single mechanical pass rather than two.

`AssistantUsageEvent` is absent on purpose — its `user` is the acting member,
not the tenant, and it stays NOT NULL forever.
"""

import pytest
from django.apps import apps

LOSING_USER = [
    "finances.Entry",
    "finances.Income",
    "finances.Category",
    "finances.PaymentMethod",
    "finances.Budget",
    "finances.InstallmentPlan",
    "finances.SystemicExpense",
    "finances.ImportBatch",
    "assistant.ChatMessage",
    "assistant.MemoryRule",
    "assistant.ReceiptDraft",
    "assistant.MemoryEmbedding",
]


@pytest.mark.parametrize("label", LOSING_USER)
def test_user_is_nullable(label):
    assert apps.get_model(label)._meta.get_field("user").null is True


def test_the_actor_column_is_not_nullable():
    """AssistantUsageEvent.user is who spent the turn. A usage event with no
    actor is meaningless, so it stays required — and it survives Task 13."""
    assert apps.get_model("assistant.AssistantUsageEvent")._meta.get_field("user").null is False
