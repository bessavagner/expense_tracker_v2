"""`user` is gone from the twelve models that only ever used it as a tenant.

`AssistantUsageEvent` keeps it: that column is the acting member, and the
throttle counts per person so that two people in one household each get their
own budget (E04 decision 1).
"""

import pytest
from django.apps import apps

LOST_USER = [
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


@pytest.mark.parametrize("label", LOST_USER)
def test_the_tenant_column_is_gone(label):
    field_names = {f.name for f in apps.get_model(label)._meta.get_fields()}

    assert "user" not in field_names
    assert "household" in field_names


@pytest.mark.parametrize("label", LOST_USER)
def test_provenance_survived_it(label):
    """`user` split into household + created_by. Dropping the first half
    without keeping the second would have thrown away review finding M5."""
    model = apps.get_model(label)
    if model._meta.label == "assistant.MemoryEmbedding":
        pytest.skip("machine-derived: no human author, asserted in test_household_columns")
    assert "created_by" in {f.name for f in model._meta.get_fields()}


def test_the_actor_column_survives():
    field_names = {
        f.name for f in apps.get_model("assistant.AssistantUsageEvent")._meta.get_fields()
    }

    assert "user" in field_names
    assert "household" in field_names


@pytest.mark.parametrize(
    "label,constraint",
    [
        ("finances.Category", "unique_category_per_household"),
        ("finances.Budget", "unique_budget_per_household"),
        ("finances.PaymentMethod", "unique_payment_method_per_household"),
        ("assistant.MemoryRule", "unique_memory_rule_per_household"),
    ],
)
def test_uniqueness_is_scoped_to_the_household(label, constraint):
    model = apps.get_model(label)
    names = {c.name for c in model._meta.constraints}

    assert constraint in names
    assert model._meta.unique_together == ()
