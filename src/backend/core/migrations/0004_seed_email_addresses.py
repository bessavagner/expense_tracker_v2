"""Every account that predates allauth gets a verified EmailAddress.

Without this, the deploy that turns on `ACCOUNT_EMAIL_VERIFICATION = "mandatory"`
silently locks out every existing user: allauth checks its own `EmailAddress`
table, which is empty for accounts created before E05, so a correct password
lands on "confirme seu e-mail" and the confirmation email is for a signup that
never happened.

Depends on allauth's `account.0001_initial` so the table exists to write into.
"""

from django.db import migrations

from core.migrations_helpers import backfill


def forwards(apps, schema_editor):
    User = apps.get_model("core", "CustomUser")
    EmailAddress = apps.get_model("account", "EmailAddress")
    created = backfill(EmailAddress, User.objects.all())
    print(f"  seeded {created} verified email address(es)")


def backwards(apps, schema_editor):
    """Deliberately a no-op.

    Deleting these rows would not restore the previous state — it would create
    a new one, in which accounts that have since verified or changed an address
    lose that record. Rolling back the *code* is enough: with allauth
    uninstalled the table is simply unread.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_customuser_email_unique"),
        ("account", "0001_initial"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
