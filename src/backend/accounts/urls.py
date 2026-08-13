from django.urls import path

from accounts.views import InvitationAcceptView, InvitationCreateView, MembersView

urlpatterns = [
    path("membros/", MembersView.as_view(), name="members"),
    path("convites/", InvitationCreateView.as_view(), name="invite_create"),
    path("convite/<str:token>/", InvitationAcceptView.as_view(), name="invite_accept"),
]
