"""Give every existing user their own household, as its owner.

Forward: one Household + one owner Membership per user that has none.
Reverse: delete every Membership and Household. That is safe *only* while no
domain model points at a household — which is true in this migration's phase
and stops being true in E04 phase 2. Phase 2's migration must therefore not
be reversed past this one without restoring from a dump.
"""

from django.db import migrations

from accounts.migrations_helpers import seed_household_for_user


def create_households(apps, schema_editor):
    User = apps.get_model("core", "CustomUser")  # noqa: N806
    Household = apps.get_model("accounts", "Household")  # noqa: N806
    Membership = apps.get_model("accounts", "Membership")  # noqa: N806

    for user in User.objects.all().iterator():
        seed_household_for_user(Household, Membership, user)


def delete_households(apps, schema_editor):
    Household = apps.get_model("accounts", "Household")  # noqa: N806
    Membership = apps.get_model("accounts", "Membership")  # noqa: N806
    Membership.objects.all().delete()
    Household.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_membership"),
        ("core", "0002_login_attempt"),
    ]

    operations = [
        migrations.RunPython(create_households, delete_households),
    ]
