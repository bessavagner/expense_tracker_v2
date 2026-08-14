"""Seed the beta plan.

E07 spec D5: MONTHLY_CREDITS is a PLACEHOLDER. Task 10 of the plan queries the
real ChatMessage/UsageInteraction distribution and replaces it with a number
set generously above the observed p99, in a NEW migration — this one is never
edited once applied. Do not ship to users on this value.
"""

from django.db import migrations

SLUG = "beta"
MONTHLY_CREDITS = 5000  # PLACEHOLDER — see the docstring.


def seed(apps, schema_editor):
    Plan = apps.get_model("accounts", "Plan")
    Plan.objects.update_or_create(
        slug=SLUG,
        defaults={"name": "Beta", "monthly_credits": MONTHLY_CREDITS, "is_default": True},
    )


def unseed(apps, schema_editor):
    apps.get_model("accounts", "Plan").objects.filter(slug=SLUG).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_plan_and_household_credits")]
    operations = [migrations.RunPython(seed, unseed)]
