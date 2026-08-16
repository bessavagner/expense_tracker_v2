"""The four metrics, the funnel, the wedge ratio and cost — on one screen.

S14-4's point is that these numbers get *looked at regularly, not computed
once*, and that cost sits next to engagement so unit economics and value are
visible together.

Staff-only, and deliberately **not** under `settings.ADMIN_URL_PATH`: that path
is a secret whose 404 must stay indistinguishable from a wrong guess
(`core.admin_gate`), and this page has no reason to live behind it. For the same
reason `login_url` is the ordinary app login rather than
`staff_member_required`'s default, which is the admin login — a redirect there
would hand an anonymous visitor the secret path in a `Location` header.

Staff are already exempt from the onboarding redirect by identity
(`accounts.middleware.onboarding_redirect_middleware`), so this route needs no
entry in `_ONBOARDING_EXEMPT_PREFIXES` — adding one would reopen exactly the
path oracle the admin gate closes.

Every number comes from `core.metrics`, which `retention_report` also calls.
Two implementations of "D7 retention" would eventually disagree, and the one on
screen would be the one nobody could check.
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView

from core import metrics


@method_decorator(staff_member_required(login_url="/accounts/login/"), name="dispatch")
class MetricsDashboardView(TemplateView):
    template_name = "core/metrics.html"

    def get_context_data(self, **kwargs):
        from accounts.models import Household

        context = super().get_context_data(**kwargs)

        excluded = metrics.excluded_shadow_households()
        cohorts = metrics.signup_cohorts()
        context["cohorts"] = [
            {
                "week": week,
                "size": len(kept),
                "d1": metrics.rolling_retention(kept, day=1),
                "d7": metrics.rolling_retention(kept, day=7),
                "d30": metrics.rolling_retention(kept, day=30),
            }
            for week, kept in (
                (week, [hh for hh in ids if hh not in excluded])
                for week, ids in sorted(cohorts.items(), reverse=True)
            )
            if kept
        ]

        funnel = metrics.funnel_counts()
        top = funnel[0][1] if funnel else 0
        context["funnel"] = [
            {
                "name": name,
                "count": count,
                # Drop-off from the step above, not from the top: "where do we
                # lose them" is a question about one transition at a time.
                "lost": (funnel[i - 1][1] - count) if i else None,
                "share": (count / top * 100) if top else None,
            }
            for i, (name, count) in enumerate(funnel)
        ]

        ai, manual = metrics.wedge_ratio()
        context["wedge"] = {
            "ai": ai,
            "manual": manual,
            "total": ai + manual,
            "share": (ai / (ai + manual) * 100) if (ai + manual) else None,
            "landing": ai >= manual,
        }

        costs = metrics.cost_per_household()
        turns = metrics.assistant_turns()
        names = dict(Household.objects.values_list("id", "name"))
        context["households"] = sorted(
            (
                {
                    "name": names.get(household_id, "—"),
                    "cost": costs.get(household_id),
                    "turns": turns.get(household_id, 0),
                }
                for household_id in set(costs) | set(turns)
            ),
            key=lambda row: row["cost"] or 0,
            reverse=True,
        )

        context["excluded"] = len(excluded)
        return context
