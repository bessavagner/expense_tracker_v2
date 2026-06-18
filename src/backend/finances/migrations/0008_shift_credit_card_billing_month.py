"""Shift existing credit-card entries one month forward.

The billing rule changed so credit-card expenses count in the month their
invoice is *paid* (the month after it closes) instead of the month it closes.
The new rule equals the old ``billing_month`` plus one month for every
credit-card branch, so existing data is migrated by a uniform +1 month shift.

Systemic entries keep their assigned month (they represent a planned monthly
expense, not a dated purchase). Cash/Pix entries are unaffected.
"""

from django.db import migrations


def _shift_month(d, months):
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    return d.replace(year=year, month=month + 1, day=1)


def _shift_credit_entries(apps, months):
    Entry = apps.get_model("finances", "Entry")
    qs = Entry.objects.filter(payment_method__type="credit_card").exclude(
        entry_type="systemic"
    )
    updates = []
    for entry in qs.iterator():
        entry.billing_month = _shift_month(entry.billing_month, months)
        updates.append(entry)
    if updates:
        Entry.objects.bulk_update(updates, ["billing_month"], batch_size=500)


def shift_forward(apps, schema_editor):
    _shift_credit_entries(apps, 1)


def shift_back(apps, schema_editor):
    _shift_credit_entries(apps, -1)


class Migration(migrations.Migration):
    dependencies = [
        ("finances", "0007_paymentmethodclosingday"),
    ]

    operations = [
        migrations.RunPython(shift_forward, shift_back),
    ]
