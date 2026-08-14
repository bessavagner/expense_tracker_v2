from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):
    """Rename only. Reversible, and no row moves — Postgres renames the table.

    E07 spec D1: `UsageInteraction` and `UsageRecord` are different grains, so
    this table is NOT extended with token counts. It stays the pre-call
    credit-accounting row.
    """

    dependencies = [
        ("accounts", "0004_invitation"),
        ("assistant", "0016_drop_redundant_household_fk_indexes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameModel(
            old_name="AssistantUsageEvent",
            new_name="UsageInteraction",
        ),
        migrations.AlterModelOptions(
            name="usageinteraction",
            options={
                "verbose_name": "interação com o assistente",
                "verbose_name_plural": "interações com o assistente",
            },
        ),
    ]
