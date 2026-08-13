"""E04 phase 4: drop the tenant column.

NOT reversible in any useful sense. The auto-generated reverse re-adds a NULL
`user` column and nothing refills it, because the information needed to do so
— which person owned which row — was exactly what `created_by` preserved and
`user` duplicated. To go back, restore from a dump; see docs/runbook.md,
"Applying a migration to Supabase".
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("finances", "0017_household_required"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="paymentmethod",
            name="unique_payment_method_per_user",
        ),
        migrations.RemoveIndex(
            model_name="entry",
            name="entry_user_billing_type_idx",
        ),
        migrations.RemoveIndex(
            model_name="entry",
            name="entry_user_date_recent_idx",
        ),
        migrations.RemoveIndex(
            model_name="income",
            name="income_user_month_idx",
        ),
        migrations.AlterUniqueTogether(
            name="budget",
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name="category",
            unique_together=set(),
        ),
        migrations.RemoveField(
            model_name="importbatch",
            name="user",
        ),
        migrations.RemoveField(
            model_name="installmentplan",
            name="user",
        ),
        migrations.RemoveField(
            model_name="systemicexpense",
            name="user",
        ),
        migrations.RemoveField(
            model_name="paymentmethod",
            name="user",
        ),
        migrations.RemoveField(
            model_name="entry",
            name="user",
        ),
        migrations.RemoveField(
            model_name="income",
            name="user",
        ),
        migrations.RemoveField(
            model_name="budget",
            name="user",
        ),
        migrations.RemoveField(
            model_name="category",
            name="user",
        ),
    ]
