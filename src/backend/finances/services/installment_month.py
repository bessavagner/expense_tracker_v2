from datetime import date

from django.db.models import Sum

from finances.models import Entry
from finances.models.entry import EntryType
from finances.models.installment_plan import InstallmentPlan


def installment_rows_for_month(user, year, month):
    """Return rows for each InstallmentPlan that has an entry in billing_month=(year,month,1).

    Each row dict:
        plan              – the InstallmentPlan
        parcela_num       – count of this plan's entries with billing_month <= target month
        num_installments  – plan.num_installments
        installment_amount – amount of the entry for this month
        remaining         – plan.total_amount minus sum of entries up to and including this month
    Ordered by plan.description.
    """
    billing_month = date(year, month, 1)

    # Plans that have at least one INSTALLMENT entry for this billing_month and user
    plans_this_month = InstallmentPlan.objects.filter(
        user=user,
        entries__entry_type=EntryType.INSTALLMENT,
        entries__billing_month=billing_month,
    ).order_by("description").distinct()

    rows = []
    for plan in plans_this_month:
        # This month's entry
        this_entry = (
            Entry.objects.filter(
                user=user,
                installment_plan=plan,
                entry_type=EntryType.INSTALLMENT,
                billing_month=billing_month,
            )
            .first()
        )
        if this_entry is None:
            continue

        # Count entries up to and including this month (parcela_num)
        parcela_num = Entry.objects.filter(
            user=user,
            installment_plan=plan,
            entry_type=EntryType.INSTALLMENT,
            billing_month__lte=billing_month,
        ).count()

        # Sum of amounts up to and including this month
        paid_agg = Entry.objects.filter(
            user=user,
            installment_plan=plan,
            entry_type=EntryType.INSTALLMENT,
            billing_month__lte=billing_month,
        ).aggregate(total=Sum("amount"))
        paid = paid_agg["total"] or 0

        rows.append(
            {
                "plan": plan,
                "entry": this_entry,
                "parcela_num": parcela_num,
                "num_installments": plan.num_installments,
                "installment_amount": this_entry.amount,
                "remaining": plan.total_amount - paid,
            }
        )

    return rows
