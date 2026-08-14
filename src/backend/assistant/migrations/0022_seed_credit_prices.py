"""Seed the credit price grid.

Ratios, not absolutes: the numbers matter only relative to the monthly grant,
which Task 10 sets from real data. A vision call is genuinely far more
expensive than a text turn, and ADVANCED more than STANDARD, so the currency
says so. Task 10's cost report is what justifies retuning these.

Sanity-check against the seeded USD prices: an image turn drives a vision
extraction plus a chat run, so it is several times a text turn's real cost.
ESSENTIAL is zero by definition, not by measurement — it is the free floor.
"""

from django.db import migrations

# (tier, kind, credits)
GRID = [
    ("advanced", "text", 3),
    ("advanced", "image", 12),
    ("standard", "text", 1),
    ("standard", "image", 4),
    ("essential", "text", 0),
    ("essential", "image", 0),
]


def seed(apps, schema_editor):
    CreditPrice = apps.get_model("assistant", "CreditPrice")
    for tier, kind, credits in GRID:
        CreditPrice.objects.update_or_create(tier=tier, kind=kind, defaults={"credits": credits})


def unseed(apps, schema_editor):
    apps.get_model("assistant", "CreditPrice").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("assistant", "0021_credit_price_and_interaction_columns")]
    operations = [migrations.RunPython(seed, unseed)]
