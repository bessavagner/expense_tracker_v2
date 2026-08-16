from django.urls import path
from django.views.generic import RedirectView

from accounts.onboarding import OnboardingSkipView, OnboardingStepView, OnboardingView
from accounts.views import (
    InvitationAcceptView,
    InvitationCreateView,
    InvitationRevokeView,
    MemberRemoveView,
)
from accounts.views_account import (
    AccountView,
    MembersTabView,
    ProfileTabView,
    SecurityTabView,
)

urlpatterns = [
    path("comecar/", OnboardingView.as_view(), name="onboarding"),
    path("comecar/<str:step>/", OnboardingStepView.as_view(), name="onboarding_step"),
    path("comecar/<str:step>/pular/", OnboardingSkipView.as_view(), name="onboarding_skip"),
    path("conta/", AccountView.as_view(), name="account"),
    path("conta/perfil/", ProfileTabView.as_view(), name="account_profile_tab"),
    path("conta/seguranca/", SecurityTabView.as_view(), name="account_security_tab"),
    path("conta/membros/", MembersTabView.as_view(), name="account_members_tab"),
    # Kept as a permanent redirect rather than deleted: this path is in the
    # installed Android TWA and in whatever bookmarks the beta made, and there
    # is no way to push a URL change to a phone that already has the app. The
    # name survives too, so any reference this epic missed still lands
    # somewhere correct.
    path(
        "membros/",
        RedirectView.as_view(pattern_name="account", permanent=True),
        name="members",
    ),
    path("membros/<uuid:pk>/remover/", MemberRemoveView.as_view(), name="member_remove"),
    path("convites/", InvitationCreateView.as_view(), name="invite_create"),
    path("convites/<uuid:pk>/cancelar/", InvitationRevokeView.as_view(), name="invite_revoke"),
    path("convite/<str:token>/", InvitationAcceptView.as_view(), name="invite_accept"),
]
