"""The Conta page and its tabs.

Kept out of `accounts/views.py` — which is about invitations and membership —
because two more epics will add tabs here: E13 a Privacidade tab (export and
deletion) and E15 a Plano tab. This module is the container they extend.

Every tab is a view with its own URL, and every one of them renders standalone
when it is hit without an `HX-Request` header. That is not a nicety: it is how
the tests reach them, and it is what keeps a tab from becoming meaningful only
inside one particular parent page.
"""

import json
import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views import View
from django.views.generic import TemplateView

from accounts.forms import ProfileForm
from accounts.models import Invitation, Membership
from accounts.permissions import is_owner
from core.privacy import delete_account

logger = logging.getLogger(__name__)


class AccountView(LoginRequiredMixin, TemplateView):
    """The shell: a heading and a tab bar. Every tab's content arrives by HTMX."""

    template_name = "accounts/account_page.html"


class _TabView(LoginRequiredMixin, TemplateView):
    """One tab: a fragment for HTMX, a whole page for a direct hit.

    `request.htmx` rather than reading the header by hand — `django_htmx`'s
    middleware is installed and `finances.views.mixins` already uses it, so
    two ways of asking the same question would be one too many.
    """

    fragment_template_name = ""
    page_template_name = "accounts/tab_page.html"
    tab_title = ""

    def get_template_names(self):
        if self.request.htmx:
            return [self.fragment_template_name]
        return [self.page_template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["fragment_template"] = self.fragment_template_name
        context["tab_title"] = self.tab_title
        return context


class ProfileTabView(_TabView):
    """Name and email address.

    The email is displayed and linked, never edited here: allauth owns that
    flow (spec D3), and reimplementing it so it looks nicer is how it gets
    subtly wrong.
    """

    fragment_template_name = "accounts/_profile_tab.html"
    tab_title = "Perfil"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("form", ProfileForm(instance=self.request.user))
        return context

    def post(self, request, *args, **kwargs):
        # `instance=request.user`, and no id in the form: the only account
        # this can ever write to is the one making the request.
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            response = self._render_fragment(request, ProfileForm(instance=request.user))
            response["HX-Trigger"] = json.dumps(
                {"showToast": {"message": "Nome salvo!", "type": "success"}}
            )
            return response
        return self._render_fragment(request, form)

    def _render_fragment(self, request, form):
        html = render_to_string(
            self.fragment_template_name,
            {"form": form, "fragment_template": self.fragment_template_name},
            request=request,
        )
        return HttpResponse(html)


class SecurityTabView(_TabView):
    """Password and second factor — status and links, never the forms.

    Spec D3, and it is the load-bearing decision of this epic: reimplementing
    a security-critical flow so it looks nicer is how it gets subtly wrong.

    No "senha alterada em ..." line, deliberately. `AbstractUser` has no
    password-changed timestamp, and adding one means a migration this epic is
    committed to not having.
    """

    fragment_template_name = "accounts/_security_tab.html"
    tab_title = "Segurança"

    def get_context_data(self, **kwargs):
        from allauth.mfa.utils import is_mfa_enabled

        context = super().get_context_data(**kwargs)
        context["mfa_enabled"] = is_mfa_enabled(self.request.user)
        return context


class MembersTabView(_TabView):
    """Who is in this household, and who has been invited.

    Visible to every member — knowing who can see the family's money is not a
    privilege. Only the owner gets the controls, and that is enforced in the
    views they post to (`OwnerRequiredMixin`), not by hiding the buttons.
    """

    fragment_template_name = "accounts/_members.html"
    tab_title = "Membros"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        household = self.request.household
        context["household"] = household
        context["memberships"] = (
            Membership.objects.filter(household=household)
            .select_related("user")
            .order_by("created_at")
        )
        context["invitations"] = [
            invitation
            for invitation in Invitation.objects.for_request(self.request)
            if invitation.is_pending
        ]
        context["viewer_is_owner"] = is_owner(self.request.user, household)
        return context


class PrivacyTabView(_TabView):
    """Everything this product knows about you, and the three buttons that
    matter: take a copy, correct it, delete it.

    Reads the inventory for the retention numbers rather than repeating them
    here. A number typed into a template is a number that drifts away from the
    job that enforces it, and this whole epic is about those two agreeing.
    """

    fragment_template_name = "accounts/_privacy_tab.html"
    tab_title = "Privacidade"

    def get_context_data(self, **kwargs):
        from assistant.models import MemoryRule
        from core.models import PolicyAcceptance
        from core.privacy import has_ai_consent, record_for

        context = super().get_context_data(**kwargs)
        context["ai_consent"] = has_ai_consent(self.request.user)
        context["memory_rules"] = MemoryRule.objects.for_request(self.request).order_by(
            "-last_used_at"
        )[:100]
        context["acceptances"] = PolicyAcceptance.objects.filter(user=self.request.user)
        context["chat_retention_days"] = record_for("assistant.ChatMessage").retention_days
        context["draft_retention_days"] = record_for("assistant.ReceiptDraft").retention_days
        return context


class AIConsentView(LoginRequiredMixin, View):
    """Grant or withdraw permission for the AI leg, and re-render the tab.

    POST only, and it names no user: the only consent this can ever write is
    the caller's own.
    """

    def post(self, request, *args, **kwargs):
        from core.privacy import set_ai_consent

        set_ai_consent(request.user, granted=request.POST.get("granted") == "1")
        return _render_privacy_fragment(request)


class MemoryRuleDeleteView(LoginRequiredMixin, View):
    """Forget one thing the assistant concluded about you.

    This is the correction right (S13-2) in its most concrete form. It deletes
    the rule's embedding too — leaving the vector behind would mean semantic
    lookup keeps finding an inference the person just told us to forget.

    404 rather than 403 for a rule in another household: whether a row exists
    over there is itself not ours to disclose.
    """

    def post(self, request, pk, *args, **kwargs):
        from assistant.models import MemoryEmbedding, MemoryRule
        from assistant.tasks import embedding_id_for

        rule = MemoryRule.objects.for_request(request).filter(pk=pk).first()
        if rule is None:
            raise Http404("regra não encontrada")

        MemoryEmbedding.objects.filter(id=embedding_id_for(rule.pk)).delete()
        rule.delete()
        return _render_privacy_fragment(request, toast="Regra apagada. O assistente esqueceu isso.")


def _render_privacy_fragment(request, toast: str | None = None) -> HttpResponse:
    """Re-render the tab after a write, the way `ProfileTabView.post` does.

    A shared helper rather than a mixin: two small views and one template name,
    and a class hierarchy would be more machinery than the thing it organises.
    """
    view = PrivacyTabView()
    view.setup(request)
    html = render_to_string(
        PrivacyTabView.fragment_template_name,
        view.get_context_data(),
        request=request,
    )
    response = HttpResponse(html)
    if toast:
        response["HX-Trigger"] = json.dumps({"showToast": {"message": toast, "type": "success"}})
    return response


class AccountDeleteView(LoginRequiredMixin, View):
    """The last screen before an irreversible act.

    GET explains what will happen — which is different depending on whether
    anyone else is in the household — and offers an export if none has been
    taken. POST does it, once the person has typed their own address.

    Typed address rather than a checkbox: a checkbox is one mis-tap, and this
    deletes a financial history that cannot be reconstructed. Same reason the
    export offer is on this page rather than in a help article.
    """

    template_name = "accounts/tab_page.html"
    fragment_template_name = "accounts/_privacy_delete.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._context(request))

    def post(self, request, *args, **kwargs):
        from django.contrib.auth import logout

        typed = (request.POST.get("confirm_email") or "").strip().lower()
        if typed != request.user.email.strip().lower():
            context = self._context(request)
            context["error"] = "Digite exatamente o e-mail da sua conta para confirmar a exclusão."
            return render(request, self.template_name, context)

        receipt = delete_account(request.user)
        # After `delete_account` the session row is already gone, so this is
        # about the request's own state rather than about the store.
        logout(request)
        logger.info("Account deletion completed from the UI: %s", receipt.email)
        return redirect("account_deleted")

    def _context(self, request):
        from finances.models import ExportJob, ExportStatus

        household = request.household
        others = (
            Membership.objects.filter(household=household)
            .exclude(user=request.user)
            .select_related("user")
            if household is not None
            else Membership.objects.none()
        )
        last_export = (
            ExportJob.objects.for_request(request)
            .filter(status=ExportStatus.DONE)
            .order_by("-created_at")
            .first()
        )
        return {
            "fragment_template": self.fragment_template_name,
            "tab_title": "Excluir conta",
            "others": others,
            "household": household,
            "last_export": last_export,
        }


class AccountDeletedView(TemplateView):
    """Deliberately not `LoginRequiredMixin`.

    Everyone who reaches this page has no account, so requiring one would
    redirect them to a login screen for credentials that no longer exist — and
    the last thing they would see is a failure.
    """

    template_name = "accounts/account_deleted.html"
