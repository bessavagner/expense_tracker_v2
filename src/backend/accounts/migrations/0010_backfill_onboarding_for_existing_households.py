from django.db import migrations

from accounts.migrations_helpers import mark_existing_households_onboarded

#: Frozen copy of `OnboardingStep` as it stands when this migration is written.
#: A data migration must not read the live enum: adding a fourth step later
#: would retroactively change what this one did on a rebuilt database.
STEPS_AT_THIS_POINT = ["income", "cards", "capture"]


def mark_pre_e11_households_onboarded(apps, schema_editor):
    mark_existing_households_onboarded(
        apps.get_model("accounts", "Household"),
        apps.get_model("accounts", "OnboardingState"),
        STEPS_AT_THIS_POINT,
    )


def unmark(apps, schema_editor):
    """Reverse by dropping only the rows this migration would have created.

    A backfilled row is recognisable: every step done, no completion
    timestamp. A household that actually finished the flow has `completed_at`
    set, and one still in it has fewer steps — neither is touched.
    """
    OnboardingState = apps.get_model("accounts", "OnboardingState")
    OnboardingState.objects.filter(
        completed_at__isnull=True, steps_done=STEPS_AT_THIS_POINT
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0009_household_projection_origin_month"),
    ]

    operations = [
        migrations.RunPython(mark_pre_e11_households_onboarded, unmark),
    ]
