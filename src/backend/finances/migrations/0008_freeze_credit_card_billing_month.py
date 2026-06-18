"""Freeze existing credit-card entries so the new billing rule is forward-only.

The billing rule changed so a credit-card expense counts in the month its
invoice is *paid* (one month after it closes). That rule must apply only to
entries created from now on: historical data was already entered with the
intended accounting month (parcelas, in particular, were typed with the
charge month, not the purchase month).

So instead of rewriting any month, this migration just pins existing
credit-card entries with ``billing_month_override=True``. That stops
``Entry.save`` from recomputing their ``billing_month`` under the new rule if
they are ever re-saved, while leaving every value exactly as it is.

Cash/Pix entries are left alone: for them the charge month always equals the
purchase month, so recomputation is a no-op. Systemic entries already set the
override themselves.
"""

from django.db import migrations


def freeze_credit_entries(apps, schema_editor):
    Entry = apps.get_model("finances", "Entry")
    Entry.objects.filter(
        payment_method__type="credit_card", billing_month_override=False
    ).update(billing_month_override=True)


def noop_reverse(apps, schema_editor):
    # Irreversible by design: we cannot tell which entries were already frozen
    # before this migration, and unfreezing would risk silent month changes on
    # the next save. The data itself is untouched, so there is nothing to undo.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("finances", "0007_paymentmethodclosingday"),
    ]

    operations = [
        migrations.RunPython(freeze_credit_entries, noop_reverse),
    ]
