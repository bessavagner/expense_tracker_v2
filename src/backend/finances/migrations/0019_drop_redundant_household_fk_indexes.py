"""Drop Django's implicit FK index on `household_id` for Entry and Income.

E03 removed exactly these indexes when the tenant column was `user`
(0008_drop_redundant_user_fk_indexes), because each is a strict prefix of the
composite that leads with the same column — so it serves no query the composite
cannot, while costing writes, disk, and sometimes a correct plan. E04 phase 2
re-created them by adding `household` as an ordinary ForeignKey. Measured at
product scale in Task 14; see docs/architecture/query-performance-baseline.md.

Only the index changes. The column, its constraint and its related_name are
untouched, so this is reversible and carries no data risk.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_household_per_existing_user"),
        ("finances", "0018_drop_user"),
    ]

    operations = [
        migrations.AlterField(
            model_name="entry",
            name="household",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="%(app_label)s_%(class)s",
                to="accounts.household",
            ),
        ),
        migrations.AlterField(
            model_name="income",
            name="household",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="%(app_label)s_%(class)s",
                to="accounts.household",
            ),
        ),
    ]
