"""Give every existing finances row the household of the user who owns it.

Forward: household from the user's owner Membership (seeded by
accounts.0003), created_by from the user. Rows whose user has no membership
are left NULL deliberately — see accounts/backfill.py.

Reverse: NULL both columns again. Safe and lossless *because* `user` is still
present in phases 2 and 3 and remains the source of truth; once phase 4 drops
`user`, reversing past this migration means restoring from a dump.
"""

from django.db import migrations

from accounts.backfill import backfill_household_columns

LABELS = [
    "finances.Entry",
    "finances.Income",
    "finances.Category",
    "finances.PaymentMethod",
    "finances.Budget",
    "finances.InstallmentPlan",
    "finances.SystemicExpense",
    "finances.ImportBatch",
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
        ("finances", "0013_household_and_created_by"),
        ("accounts", "0003_household_per_existing_user"),
    ]

    operations = [
        migrations.RunPython(fill, unfill),
    ]
