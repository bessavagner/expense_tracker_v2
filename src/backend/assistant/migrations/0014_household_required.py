"""E04 phase 4: household becomes NOT NULL.

The back-fill (0011) filled every row whose user held an owner membership, and
accounts.0003 seeded a household for every user that existed. Anything still
NULL here is a row the back-fill deliberately skipped — see accounts/backfill.py
— and it must be looked at by a person, not invented by a migration.
"""

import django.db.models.deletion
from django.db import migrations, models

LABELS = [
    "assistant.ChatMessage",
    "assistant.MemoryRule",
    "assistant.ReceiptDraft",
    "assistant.MemoryEmbedding",
    "assistant.AssistantUsageEvent",
]


def refuse_if_any_row_is_tenant_less(apps, schema_editor):
    """Fail first, loudly, with the count.

    A NOT NULL migration that dies halfway through production data is the worst
    outcome available: the ALTER is already partly applied and the operator is
    reading a Postgres error rather than a list of what to fix.
    """
    unfilled = {}
    for label in LABELS:
        count = apps.get_model(label).objects.filter(household__isnull=True).count()
        if count:
            unfilled[label] = count
    if unfilled:
        raise RuntimeError(
            "Refusing to add NOT NULL: these rows have no household. Run the "
            "back-fill, or decide who owns them, then re-run this migration. "
            f"{unfilled}"
        )


def noop(apps, schema_editor):
    """Reversing NOT NULL loses nothing; there is nothing to undo here."""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_household_per_existing_user"),
        ("assistant", "0013_user_nullable"),
    ]

    operations = [
        migrations.RunPython(refuse_if_any_row_is_tenant_less, noop),
        migrations.AlterField(
            model_name="assistantusageevent",
            name="household",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="%(app_label)s_%(class)s",
                to="accounts.household",
            ),
        ),
        migrations.AlterField(
            model_name="chatmessage",
            name="household",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="%(app_label)s_%(class)s",
                to="accounts.household",
            ),
        ),
        migrations.AlterField(
            model_name="memoryembedding",
            name="household",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="%(app_label)s_%(class)s",
                to="accounts.household",
            ),
        ),
        migrations.AlterField(
            model_name="memoryrule",
            name="household",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="%(app_label)s_%(class)s",
                to="accounts.household",
            ),
        ),
        migrations.AlterField(
            model_name="receiptdraft",
            name="household",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="%(app_label)s_%(class)s",
                to="accounts.household",
            ),
        ),
    ]
