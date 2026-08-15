"""The guided setup — three steps, every one skippable, progress resumable.

Server-rendered with HTMX rather than a React island, matching every other form
surface in this product (`templates/settings/`, `templates/account/`). The one
React island a new user meets is the chat, which is where this flow
deliberately hands them off: S11-3's last requirement is that setup ends at the
activation moment, not at an empty dashboard.

Every step writes through the ordinary models, so nothing here is a parallel
write path that could drift from what the settings screens do.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from accounts.models import OnboardingState, OnboardingStep
from core.events import EventName, emit, emit_once
from finances.models import Income, PaymentMethod
from finances.models.payment_method import PaymentType

#: Where the flow lets go of the user. The query string is what makes the
#: dashboard open the chat with the camera ready (Task 8) instead of showing
#: the empty cards S11-3 explicitly refuses to end on.
ACTIVATION_HANDOFF_URL = "/?comecar=foto"


class OnboardingView(LoginRequiredMixin, TemplateView):
    """Whichever step this household has not been asked yet."""

    template_name = "onboarding/onboarding_page.html"

    def get(self, request, *args, **kwargs):
        state = OnboardingState.for_household(request.household)
        if state.is_complete:
            return HttpResponseRedirect("/")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        state = OnboardingState.for_household(self.request.household)
        context["state"] = state
        context["step"] = state.next_step()
        context["step_number"] = len(state.steps_done or []) + 1
        context["step_total"] = len(OnboardingStep)
        return context


class _StepView(LoginRequiredMixin, View):
    """Shared plumbing: mark the step, emit, and go wherever the flow goes next."""

    def _advance(self, request, step, action):
        state = OnboardingState.for_household(request.household)
        state.mark(step)
        emit(
            EventName.ONBOARDING_STEP,
            household=request.household,
            user=request.user,
            metadata={"step": str(step), "action": action},
        )
        if state.is_complete:
            emit_once(
                EventName.ONBOARDING_DONE,
                household=request.household,
                user=request.user,
            )
            return HttpResponseRedirect(ACTIVATION_HANDOFF_URL)
        return HttpResponseRedirect(reverse("onboarding"))


class OnboardingStepView(_StepView):
    """The user filled a step in."""

    def post(self, request, step, *args, **kwargs):
        if step == OnboardingStep.INCOME:
            self._save_income(request)
        elif step == OnboardingStep.CARDS:
            self._save_card(request)
        # CAPTURE has nothing to save: its "submit" is the handoff itself.
        return self._advance(request, step, "done")

    def _save_income(self, request):
        name = (request.POST.get("name") or "").strip() or "Renda"
        try:
            amount = Decimal(request.POST.get("amount") or "")
        except InvalidOperation:
            return
        if amount <= 0:
            return
        Income.objects.create(
            household=request.household,
            created_by=request.user,
            name=name,
            amount=amount,
            month=date.today().replace(day=1),
            is_recurring=True,
            recurrence_start=date.today().replace(day=1),
        )

    def _save_card(self, request):
        name = (request.POST.get("name") or "").strip()
        if not name:
            return
        try:
            closing_day = int(request.POST.get("closing_day") or "")
        except ValueError:
            return
        if not 1 <= closing_day <= 31:
            return
        PaymentMethod.objects.get_or_create(
            household=request.household,
            name=name,
            defaults={
                "type": PaymentType.CREDIT_CARD,
                "closing_day": closing_day,
                "created_by": request.user,
            },
        )


class OnboardingSkipView(_StepView):
    """The user chose not to answer. Nothing is written; the flow moves on.

    S11-3 requires skipping not to break the product, and it does not: the
    starter catalogue from Task 3 already makes the household usable, so every
    step here is an improvement rather than a prerequisite.
    """

    def post(self, request, step, *args, **kwargs):
        return self._advance(request, step, "skipped")
