from django.urls import path

from accounts.onboarding import OnboardingSkipView, OnboardingStepView, OnboardingView
from accounts.views import (
    InvitationAcceptView,
    InvitationCreateView,
    InvitationRevokeView,
    MemberRemoveView,
    MembersView,
)
from accounts.views_account import ProfileTabView, SecurityTabView

urlpatterns = [
    path("comecar/", OnboardingView.as_view(), name="onboarding"),
    path("comecar/<str:step>/", OnboardingStepView.as_view(), name="onboarding_step"),
    path("comecar/<str:step>/pular/", OnboardingSkipView.as_view(), name="onboarding_skip"),
    path("conta/perfil/", ProfileTabView.as_view(), name="account_profile_tab"),
    path("conta/seguranca/", SecurityTabView.as_view(), name="account_security_tab"),
    path("membros/", MembersView.as_view(), name="members"),
    path("membros/<uuid:pk>/remover/", MemberRemoveView.as_view(), name="member_remove"),
    path("convites/", InvitationCreateView.as_view(), name="invite_create"),
    path("convites/<uuid:pk>/cancelar/", InvitationRevokeView.as_view(), name="invite_revoke"),
    path("convite/<str:token>/", InvitationAcceptView.as_view(), name="invite_accept"),
]
