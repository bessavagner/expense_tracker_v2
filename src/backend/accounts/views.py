"""Invitation and membership screens.

The accept view is deliberately reachable by an anonymous visitor: the invitee
may not have an account yet, and bouncing them to a login page loses the token
in the round trip through their email client. Instead the token stays in the
URL, and `?next=` carries it back through signup and verification.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from accounts.emails import send_invitation
from accounts.invitations import (
    InvitationUnusable,
    create_invitation,
    invitation_for_token,
    redeem_invitation,
)
from accounts.models import Invitation, Membership
from accounts.permissions import OwnerRequiredMixin, is_owner


class MembersView(LoginRequiredMixin, TemplateView):
    """Who is in this household, and who has been invited.

    Visible to every member — knowing who can see the family's money is not a
    privilege. Only the owner gets the controls, and that is enforced in the
    views they post to, not by hiding the buttons.
    """

    template_name = "accounts/members.html"

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


class InvitationCreateView(OwnerRequiredMixin, View):
    """An owner invites someone by email."""

    def post(self, request, *args, **kwargs):
        email = (request.POST.get("email") or "").strip()
        if not email:
            messages.error(request, "Informe um e-mail.")
            return HttpResponseRedirect(reverse("members"))

        invitation, raw_token = create_invitation(
            household=request.household, invited_by=request.user, email=email
        )
        send_invitation(invitation, raw_token, request)
        messages.success(request, f"Convite enviado para {email}.")
        return HttpResponseRedirect(reverse("members"))


class InvitationAcceptView(View):
    """The page an invitation link opens.

    GET is safe and idempotent — it only describes the invitation — because an
    email client or a link scanner will fetch it before a human sees it, and a
    scanner must not be able to spend the token. Redemption is the POST.
    """

    def get(self, request, token, *args, **kwargs):
        invitation = invitation_for_token(token)
        if invitation is None or not invitation.is_pending:
            return render(request, "accounts/invite_invalid.html", status=404)
        return render(
            request,
            "accounts/invite_landing.html",
            {"invitation": invitation, "token": token, "next": request.path},
        )

    def post(self, request, token, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied
        try:
            membership = redeem_invitation(token, request.user)
        except InvitationUnusable:
            return render(request, "accounts/invite_invalid.html", status=404)

        # Make the household they just joined the one they are looking at —
        # otherwise the middleware's oldest-membership fallback would leave
        # them staring at their own empty ledger and wondering what happened.
        from accounts.middleware import ACTIVE_HOUSEHOLD_SESSION_KEY

        request.session[ACTIVE_HOUSEHOLD_SESSION_KEY] = str(membership.household.id)
        messages.success(request, f"Você agora faz parte da {membership.household.name}.")
        return HttpResponseRedirect("/")
