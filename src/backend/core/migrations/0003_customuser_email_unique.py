from django.db import migrations, models


def fill_blank_emails(apps, schema_editor):
    """Give every address-less account a reserved, non-deliverable placeholder.

    `.invalid` is reserved by RFC 2606 and can never resolve, so a placeholder
    can neither collide with a real address nor accidentally receive mail. The
    operator repairs these by hand — see docs/runbook.md — and until they do,
    the account simply cannot log in, which is the correct failure.
    """
    User = apps.get_model("core", "CustomUser")
    for user in User.objects.filter(models.Q(email="") | models.Q(email__isnull=True)):
        User.objects.filter(pk=user.pk).update(email=f"{user.username}@sem-email.invalid")


def unfill(apps, schema_editor):
    User = apps.get_model("core", "CustomUser")
    User.objects.filter(email__endswith="@sem-email.invalid").update(email="")


class Migration(migrations.Migration):
    dependencies = [("core", "0002_login_attempt")]

    operations = [
        migrations.RunPython(fill_blank_emails, unfill),
        migrations.AlterField(
            model_name="customuser",
            name="email",
            field=models.EmailField(max_length=254, unique=True, verbose_name="endereço de e-mail"),
        ),
    ]
