from django.urls import path

from assistant.views import chat_view, history_view, tier_view, usage_view

app_name = "assistant"

urlpatterns = [
    path("chat/", chat_view, name="chat"),
    path("history/", history_view, name="history"),
    path("usage/", usage_view, name="usage"),
    path("tier/", tier_view, name="tier"),
]
