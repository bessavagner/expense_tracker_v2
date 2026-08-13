"""E04 phase 4: drop the tenant column.

NOT reversible in any useful sense. The auto-generated reverse re-adds a NULL
`user` column and nothing refills it, because the information needed to do so
— which person owned which row — was exactly what `created_by` preserved and
`user` duplicated. To go back, restore from a dump; see docs/runbook.md,
"Applying a migration to Supabase".

`AssistantUsageEvent` is untouched: its `user` is the acting member, not the
tenant, and the throttle counts per person (E04 decision 1).
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0014_household_required"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="chatmessage",
            name="chat_user_recent_idx",
        ),
        migrations.RemoveIndex(
            model_name="receiptdraft",
            name="draft_user_status_recent_idx",
        ),
        migrations.AlterUniqueTogether(
            name="memoryrule",
            unique_together=set(),
        ),
        migrations.RemoveField(
            model_name="memoryembedding",
            name="user",
        ),
        migrations.RemoveField(
            model_name="chatmessage",
            name="user",
        ),
        migrations.RemoveField(
            model_name="receiptdraft",
            name="user",
        ),
        migrations.RemoveField(
            model_name="memoryrule",
            name="user",
        ),
    ]
