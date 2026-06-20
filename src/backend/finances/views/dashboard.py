from datetime import date

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from finances.services.category_stats import category_moving_averages_named
from finances.services.projection import build_projection


def _sparkline_points(values, width=120, height=28):
    if not values:
        return ""
    nums = [float(v) for v in values]
    lo, hi = min(nums), max(nums)
    span = (hi - lo) or 1.0
    step = width / max(len(nums) - 1, 1)
    pts = [
        f"{i * step:.1f},{height - (v - lo) / span * height:.1f}"
        for i, v in enumerate(nums)
    ]
    return " ".join(pts)


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/dashboard_page.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = date.today()
        year = int(self.request.GET.get("year", today.year))
        month = int(self.request.GET.get("month", today.month))
        context["current_year"] = year
        context["current_month"] = month
        context["months"] = list(range(1, 13))
        context["year_range"] = range(2024, today.year + 2)
        context["api_params"] = f"year={year}&month={month}"

        cur = today.replace(day=1)
        proj = build_projection(self.request.user, cur, 6, today=today)
        context["projection_row"] = proj[0] if proj else None
        trend = [{"month": r["month"], "acumulado": r["acumulado"],
                  "acumulado_estimado": r["acumulado_estimado"]} for r in proj]
        context["projection_trend"] = trend
        context["sparkline_points"] = _sparkline_points(
            [t["acumulado_estimado"] for t in trend]
        )
        context["category_averages_named"] = category_moving_averages_named(self.request.user)
        return context
