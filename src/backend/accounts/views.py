"""Invitation and membership screens.

The accept view is deliberately reachable by an anonymous visitor: the invitee
may not have an account yet, and bouncing them to a login page loses the token
in the round trip through their email client. Instead the token stays in the
URL, and `?next=` carries it back through signup and verification.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseBadRequest, HttpResponseRedirect
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
    revoke_invitation,
)
from accounts.models import Invitation, Membership, Role
from accounts.permissions import OwnerRequiredMixin, is_owner

#: Where the landing page leaves the token so signup can find it. The URL is
#: the primary carrier (`?next=`); this is the backup for the case that URL
#: cannot survive — a verification link opened later, a redirect chain that
#: drops the query string.
PENDING_INVITE_SESSION_KEY = "pending_invitation_token"


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
        request.session[PENDING_INVITE_SESSION_KEY] = token
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


class InvitationRevokeView(OwnerRequiredMixin, View):
    """Withdraw a pending invitation."""

    def post(self, request, pk, *args, **kwargs):
        # Scoped, not filtered by hand: an invitation belonging to another
        # household must be *invisible* (404), never merely refused (403) —
        # a 403 confirms the id exists.
        invitation = Invitation.objects.for_request(request).filter(pk=pk).first()
        if invitation is None:
            raise Http404
        revoke_invitation(invitation)
        messages.success(request, f"Convite para {invitation.email} cancelado.")
        return HttpResponseRedirect(reverse("members"))


class MemberRemoveView(OwnerRequiredMixin, View):
    """Remove someone from the household.

    Deleting the Membership is the entire mechanism. E04 resolves the active
    household from memberships on every request and every scoped queryset
    fails closed to `none()`, so access ends on the next request — no session
    to purge, no cache to bust. The household's ledger is untouched:
    `created_by` is SET_NULL precisely so a person leaving does not take the
    family's financial history with them.
    """

    def post(self, request, pk, *args, **kwargs):
        membership = (
            Membership.objects.filter(pk=pk, household=request.household)
            .select_related("user")
            .first()
        )
        if membership is None:
            raise Http404

        if membership.role == Role.OWNER:
            remaining_owners = (
                Membership.objects.filter(household=request.household, role=Role.OWNER)
                .exclude(pk=membership.pk)
                .count()
            )
            if remaining_owners == 0:
                # E04's open question 3 and E13 own the real semantics of a
                # household losing its last owner. Refusing is the only answer
                # here that cannot leave one orphaned.
                return HttpResponseBadRequest(
                    "A casa precisa de pelo menos um dono. Promova outra pessoa antes."
                )

        email = membership.user.email
        membership.delete()
        messages.success(request, f"{email} não faz mais parte da casa.")
        return HttpResponseRedirect(reverse("members"))
