from datetime import date
from decimal import Decimal

from django.db.models import Case, DecimalField, Sum, Value, When
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from finances.models import Category, Entry, Income


def _get_month_params(request):
    """Extract year/month from query params, defaulting to current month."""
    today = date.today()
    year = int(request.query_params.get("year", today.year))
    month = int(request.query_params.get("month", today.month))
    return year, month, date(year, month, 1)


class SummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        user = request.user

        income = Income.objects.filter(user=user, month=billing_month).aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0")

        _decimal = DecimalField()
        totals = Entry.objects.filter(user=user, billing_month=billing_month).aggregate(
            expenses=Sum(
                Case(When(amount__gt=0, then="amount"), default=Value(0), output_field=_decimal)
            ),
            returns=Sum(
                Case(When(amount__lt=0, then="amount"), default=Value(0), output_field=_decimal)
            ),
        )
        expenses = totals["expenses"] or Decimal("0")
        returns = abs(totals["returns"] or Decimal("0"))

        total_ceiling = Category.objects.filter(user=user).aggregate(total=Sum("budget_ceiling"))[
            "total"
        ] or Decimal("1")
        budget_pct = round(float(expenses) / float(total_ceiling) * 100, 1) if total_ceiling else 0

        return Response(
            {
                "income": f"{income:.2f}",
                "expenses": f"{expenses:.2f}",
                "returns": f"{returns:.2f}",
                "balance": f"{income - expenses + returns:.2f}",
                "budget_pct": budget_pct,
            }
        )


class TopCategoriesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        user = request.user

        category_totals = (
            Entry.objects.filter(user=user, billing_month=billing_month, amount__gt=0)
            .values("category__name")
            .annotate(total=Sum("amount"))
            .order_by("-total")[:5]
        )

        total = sum(ct["total"] for ct in category_totals) or Decimal("1")
        result = [
            {
                "name": ct["category__name"],
                "amount": f"{ct['total']:.2f}",
                "pct": round(float(ct["total"]) / float(total) * 100, 1),
            }
            for ct in category_totals
        ]
        return Response(result)


class EvolutionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        user = request.user

        # Build list of 6 months going back from billing_month
        months = []
        current = billing_month
        for _ in range(6):
            months.append(current)
            if current.month == 1:
                current = date(current.year - 1, 12, 1)
            else:
                current = date(current.year, current.month - 1, 1)

        # Two bulk queries instead of 12
        entry_totals = {
            row["billing_month"]: row["total"]
            for row in Entry.objects.filter(user=user, billing_month__in=months, amount__gt=0)
            .values("billing_month")
            .annotate(total=Sum("amount"))
        }
        income_totals = {
            row["month"]: row["total"]
            for row in Income.objects.filter(user=user, month__in=months)
            .values("month")
            .annotate(total=Sum("amount"))
        }

        result = [
            {
                "month": f"{m:%Y-%m}",
                "expenses": f"{entry_totals.get(m, Decimal('0')):.2f}",
                "income": f"{income_totals.get(m, Decimal('0')):.2f}",
            }
            for m in reversed(months)  # oldest first
        ]
        return Response(result)


class AlertsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        user = request.user

        alerts = []

        # Budget alerts
        category_totals = (
            Entry.objects.filter(user=user, billing_month=billing_month, amount__gt=0)
            .values("category__name", "category__budget_ceiling")
            .annotate(total=Sum("amount"))
        )

        ok_count = 0
        for ct in category_totals:
            ceiling = ct["category__budget_ceiling"]
            if not ceiling or ceiling <= 0:
                ok_count += 1
                continue
            ratio = ct["total"] / ceiling
            if ratio >= 1:
                over = ct["total"] - ceiling
                alerts.append(
                    {
                        "severity": "danger",
                        "message": f"{ct['category__name']} ultrapassou teto em R$ {over:.2f}",
                    }
                )
            elif ratio >= Decimal("0.9"):
                alerts.append(
                    {
                        "severity": "warning",
                        "message": (
                            f"{ct['category__name']} em {ratio * 100:.0f}% do teto "
                            f"(R$ {ct['total']:.0f} / R$ {ceiling:.0f})"
                        ),
                    }
                )
            else:
                ok_count += 1

        # Installment info
        active_entries = Entry.objects.filter(
            user=user,
            billing_month=billing_month,
            entry_type="installment",
        )
        if active_entries.exists():
            plan_count = active_entries.values("installment_plan").distinct().count()
            installment_total = active_entries.aggregate(total=Sum("amount"))["total"] or Decimal(
                "0"
            )
            alerts.append(
                {
                    "severity": "info",
                    "message": f"{plan_count} parcelas ativas, R$ {installment_total:.0f} este mês",
                }
            )

        if ok_count > 0:
            alerts.append(
                {
                    "severity": "success",
                    "message": f"{ok_count} categorias dentro do orçamento",
                }
            )

        # Sort: danger first, then warning, info, success
        severity_order = {"danger": 0, "warning": 1, "info": 2, "success": 3}
        alerts.sort(key=lambda a: severity_order.get(a["severity"], 4))

        return Response(alerts)


class RecentEntriesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        user = request.user

        entries = (
            Entry.objects.filter(user=user, billing_month=billing_month)
            .select_related("category")
            .order_by("-date", "-created_at")[:5]
        )
        result = [
            {
                "date": f"{e.date:%d/%m}",
                "description": e.description,
                "amount": f"{e.amount:.2f}",
                "category": e.category.name,
            }
            for e in entries
        ]
        return Response(result)


class InstallmentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        user = request.user

        # Find installment entries for this month
        installment_entries = Entry.objects.filter(
            user=user,
            billing_month=billing_month,
            entry_type="installment",
            installment_plan__isnull=False,
        ).select_related("installment_plan")

        # Pre-fetch all installment plan entries in a single query
        plan_ids = [e.installment_plan_id for e in installment_entries]
        plan_months_lookup: dict[int, list] = {}
        for plan_id, bmonth in (
            Entry.objects.filter(installment_plan_id__in=plan_ids)
            .order_by("billing_month")
            .values_list("installment_plan_id", "billing_month")
        ):
            plan_months_lookup.setdefault(plan_id, []).append(bmonth)

        plans = []
        monthly_total = Decimal("0")
        for entry in installment_entries:
            plan = entry.installment_plan
            months_list = plan_months_lookup.get(plan.id, [])
            try:
                current_num = months_list.index(billing_month) + 1
            except ValueError:
                current_num = 0

            plans.append(
                {
                    "description": plan.description,
                    "current": current_num,
                    "total": plan.num_installments,
                    "amount": f"{entry.amount:.2f}",
                }
            )
            monthly_total += entry.amount

        return Response(
            {
                "plans": plans,
                "monthly_total": f"{monthly_total:.2f}",
            }
        )
