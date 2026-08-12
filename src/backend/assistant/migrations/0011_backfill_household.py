"""Give every existing assistant row the household of the user who owns it.

See finances/migrations/0014_backfill_household.py for the shape and the
reversibility note. AssistantUsageEvent and MemoryEmbedding take household
only — neither has a created_by column.
"""

from django.db import migrations

from accounts.backfill import backfill_household_columns

LABELS = [
    "assistant.ChatMessage",
    "assistant.MemoryRule",
    "assistant.ReceiptDraft",
    "assistant.MemoryEmbedding",
    "assistant.AssistantUsageEvent",
]


def fill(apps, schema_editor):
    Membership = apps.get_model("accounts", "Membership")
    models_by_label = {label: apps.get_model(label) for label in LABELS}
    backfill_household_columns(Membership, models_by_label)


def unfill(apps, schema_editor):
    for label in LABELS:
        model = apps.get_model(label)
        updates = {"household_id": None}
        if any(f.name == "created_by" for f in model._meta.get_fields()):
            updates["created_by_id"] = None
        model.objects.update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0010_household_and_created_by"),
        ("accounts", "0003_household_per_existing_user"),
    ]

    operations = [
        migrations.RunPython(fill, unfill),
    ]
