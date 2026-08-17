"""The two documents, served to anyone.

Public on purpose and by necessity: somebody deciding whether to sign up has to
be able to read them, and the signup form links both. `TemplateView` with no
`LoginRequiredMixin`, and both paths are added to
`accounts.middleware._ONBOARDING_EXEMPT_PREFIXES` — otherwise a signed-in user
mid-setup, which is every new account, would be redirected away from the notice
they just clicked.

Everything factual comes from `core.privacy`. The prose is hand-written; the
purposes, the lawful bases, the retention periods and the sub-processors are
rendered from the same lists the code enforces.
"""

from django.conf import settings
from django.views.generic import TemplateView

from core.privacy import INVENTORY, Basis, Disposal, purgeable
from core.privacy.subprocessors import SUBPROCESSORS


class PrivacyNoticeView(TemplateView):
    template_name = "legal/privacidade.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["controller"] = settings.PRIVACY_CONTROLLER
        context["version"] = settings.PRIVACY_POLICY_VERSION
        context["purposes"] = [
            record for record in INVENTORY if record.disposal is not Disposal.NONE
        ]
        context["bases"] = list(Basis)
        # `retention_days == 0` is the expired-session sweep — true, and not
        # something to put in a table of promises about how long we keep things.
        context["retentions"] = [record for record in purgeable() if record.retention_days]
        context["subprocessors"] = SUBPROCESSORS
        return context


class TermsView(TemplateView):
    template_name = "legal/termos.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["controller"] = settings.PRIVACY_CONTROLLER
        context["version"] = settings.TERMS_VERSION
        return context
