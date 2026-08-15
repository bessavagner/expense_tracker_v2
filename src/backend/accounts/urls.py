from django.urls import path

from accounts.onboarding import OnboardingView
from accounts.views import (
    InvitationAcceptView,
    InvitationCreateView,
    InvitationRevokeView,
    MemberRemoveView,
    MembersView,
)

urlpatterns = [
    path("comecar/", OnboardingView.as_view(), name="onboarding"),
    path("membros/", MembersView.as_view(), name="members"),
    path("membros/<uuid:pk>/remover/", MemberRemoveView.as_view(), name="member_remove"),
    path("convites/", InvitationCreateView.as_view(), name="invite_create"),
    path("convites/<uuid:pk>/cancelar/", InvitationRevokeView.as_view(), name="invite_revoke"),
    path("convite/<str:token>/", InvitationAcceptView.as_view(), name="invite_accept"),
]
