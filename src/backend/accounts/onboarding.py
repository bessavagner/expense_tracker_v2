"""The guided setup — three steps, every one skippable, progress resumable.

Server-rendered with HTMX rather than a React island, matching every other
form surface in this product (`templates/settings/`, `templates/account/`).
The one React island a new user meets is the chat, which is where this flow
deliberately hands them off.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from accounts.models import OnboardingState


class OnboardingView(LoginRequiredMixin, TemplateView):
    """Whichever step this household has not been asked yet."""

    template_name = "onboarding/onboarding_page.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        state = OnboardingState.for_household(self.request.household)
        context["state"] = state
        context["step"] = state.next_step()
        return context
