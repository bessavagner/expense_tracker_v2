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

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.generic import TemplateView

from accounts.forms import ProfileForm


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
