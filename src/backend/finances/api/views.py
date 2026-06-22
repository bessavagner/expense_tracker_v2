from datetime import date
from decimal import Decimal

from django.db.models import Case, DecimalField, Sum, Value, When
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from finances.models import Category, Entry, Income
from finances.services.category_stats import category_moving_averages, diverse_savings_for_month
from finances.services.daily_trend import daily_spend_trend
from finances.services.projection import build_projection
from finances.services.whatif import add_months


def _get_month_params(request):
    """Extract year/month from query params, defaulting to current month."""
    today = date.today()
    year = int(request.query_params.get("year", today.year))
    month = int(request.query_params.get("month", today.month))
    return year, month, date(year, month, 1)


class SummaryView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _month_totals(user, billing_month):
        _decimal = DecimalField()
        income = Income.objects.filter(user=user, month=billing_month).aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0")
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
        balance = income - expenses + returns
        return {
            "income": income,
            "expenses": expenses,
            "returns": returns,
            "balance": balance,
        }

    @staticmethod
    def _delta_pct(cur, prev):
        if prev == 0:
            return None
        return round(float(cur - prev) / float(prev) * 100, 1)

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        user = request.user

        cur = self._month_totals(user, billing_month)
        prev = self._month_totals(user, add_months(billing_month, -1))

        total_ceiling = Category.objects.filter(user=user).aggregate(total=Sum("budget_ceiling"))[
            "total"
        ] or Decimal("0")
        budget_pct = (
            round(float(cur["expenses"]) / float(total_ceiling) * 100, 1)
            if total_ceiling > 0
            else None
        )

        return Response(
            {
                "income": f"{cur['income']:.2f}",
                "expenses": f"{cur['expenses']:.2f}",
                "returns": f"{cur['returns']:.2f}",
                "balance": f"{cur['balance']:.2f}",
                "budget_pct": budget_pct,
                "prev": {k: f"{v:.2f}" for k, v in prev.items()},
                "delta_pct": {
                    k: self._delta_pct(cur[k], prev[k]) for k in cur
                },
            }
        )


class TopCategoriesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        user = request.user

        category_totals = (
            Entry.objects.filter(user=user, billing_month=billing_month, amount__gt=0)
            .values("category__id", "category__name")
            .annotate(total=Sum("amount"))
            .order_by("-total")[:5]
        )

        # 3-month moving average per category (window before this month) so the
        # card can show whether the user is spending above/below their usual.
        averages = category_moving_averages(user, window=3, as_of=billing_month)

        # All percentages are relative to the month's GRAND total (every positive
        # entry), so the top-N slices plus "Outros" sum to 100% in the donut legend.
        grand_total = (
            Entry.objects.filter(user=user, billing_month=billing_month, amount__gt=0)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0")
        )
        pct_base = grand_total or Decimal("1")
        result = [
            {
                "name": ct["category__name"],
                "amount": f"{ct['total']:.2f}",
                "pct": round(float(ct["total"]) / float(pct_base) * 100, 1),
                "avg_3m": (
                    f"{averages[ct['category__id']]:.2f}"
                    if ct["category__id"] in averages
                    else None
                ),
            }
            for ct in category_totals
        ]
        shown_total = sum((ct["total"] for ct in category_totals), Decimal("0"))
        remainder = grand_total - shown_total
        if remainder > 0:
            result.append(
                {
                    "name": "Outros",
                    "amount": f"{remainder:.2f}",
                    "pct": round(float(remainder) / float(pct_base) * 100, 1),
                    "avg_3m": None,
                }
            )
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
        _decimal = DecimalField()
        entry_rows = (
            Entry.objects.filter(user=user, billing_month__in=months)
            .values("billing_month")
            .annotate(
                expenses=Sum(
                    Case(When(amount__gt=0, then="amount"), default=Value(0), output_field=_decimal)
                ),
                returns=Sum(
                    Case(When(amount__lt=0, then="amount"), default=Value(0), output_field=_decimal)
                ),
            )
        )
        entry_totals = {r["billing_month"]: r for r in entry_rows}
        income_totals = {
            row["month"]: row["total"]
            for row in Income.objects.filter(user=user, month__in=months)
            .values("month")
            .annotate(total=Sum("amount"))
        }

        result = [
            {
                "month": f"{m:%Y-%m}",
                "expenses": f"{(entry_totals.get(m, {}).get('expenses') or Decimal('0')):.2f}",
                "income": f"{income_totals.get(m, Decimal('0')):.2f}",
                "returns": f"{abs(entry_totals.get(m, {}).get('returns') or Decimal('0')):.2f}",
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

        # Budget alerts (per-budget, plus individual alerts for orphan categories)
        from finances.services.budget_stats import (
            budget_spend_for_month,
            orphan_category_spend_for_month,
        )

        ok_count = 0

        def _emit(label, spent, cap, pct, status):
            nonlocal ok_count
            if status == "error":
                over = spent - cap
                alerts.append({
                    "severity": "danger",
                    "message": f"{label} ultrapassou teto em R$ {over:.2f}",
                })
            elif status == "warning":
                alerts.append({
                    "severity": "warning",
                    "message": f"{label} em {pct}% do teto (R$ {spent:.0f} / R$ {cap:.0f})",
                })
            else:
                ok_count += 1

        for row in budget_spend_for_month(user, billing_month):
            _emit(row["name"], row["spent"], row["amount"], row["pct"], row["status"])
        for row in orphan_category_spend_for_month(user, billing_month):
            _emit(row["name"], row["spent"], row["ceiling"], row["pct"], row["status"])

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
                    "message": f"{ok_count} orçamentos dentro do teto",
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


class DiverseSavingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        data = diverse_savings_for_month(request.user, billing_month)
        return Response(
            {
                "baseline": f"{data['baseline']:.2f}",
                "actual": f"{data['actual']:.2f}",
                "economia": f"{data['economia']:.2f}",
                "has_baseline": data["has_baseline"],
            }
        )


class DailyTrendView(APIView):
    permission_classes = [IsAuthenticated]
    ALLOWED = (7, 15, 30, 90)

    def get(self, request):
        try:
            period = int(request.query_params.get("period", 30))
        except (TypeError, ValueError):
            period = 30
        if period not in self.ALLOWED:
            period = 30
        series = daily_spend_trend(request.user, period=period)
        return Response(
            {
                "period": period,
                "series": [
                    {
                        "date": f"{p['date']:%Y-%m-%d}",
                        "median": f"{p['median']:.2f}",
                        "p25": f"{p['p25']:.2f}",
                        "p75": f"{p['p75']:.2f}",
                    }
                    for p in series
                ],
            }
        )


class ProjectionCardView(APIView):
    """Forward-looking projection for the dashboard card: the running balance
    (acumulado) trajectory over a 6-month horizon, real vs estimated.

    ``acumulado`` follows posted entries; ``acumulado_estimado`` substitutes the
    per-category 3-month average for the diversas not yet spent — so the user sees
    where they're heading on their typical spending, not just what's posted.
    """

    permission_classes = [IsAuthenticated]
    HORIZON = 6

    def get(self, request):
        year, month, billing_month = _get_month_params(request)
        rows = build_projection(request.user, billing_month, self.HORIZON)
        if not rows:
            return Response({"series": []})

        series = [
            {
                "month": f"{r['month']:%Y-%m}",
                "acumulado": f"{r['acumulado']:.2f}",
                "acumulado_estimado": f"{r['acumulado_estimado']:.2f}",
            }
            for r in rows
        ]
        first, last = rows[0], rows[-1]
        delta = last["acumulado_estimado"] - first["acumulado_estimado"]
        return Response(
            {
                "month_label": f"{first['month']:%m/%Y}",
                "end_label": f"{last['month']:%m/%Y}",
                "saldo_mes": f"{first['saldo_projetado']:.2f}",
                "acumulado": f"{first['acumulado']:.2f}",
                "acumulado_estimado": f"{first['acumulado_estimado']:.2f}",
                "end_acumulado_estimado": f"{last['acumulado_estimado']:.2f}",
                "delta": f"{delta:.2f}",
                "series": series,
            }
        )
