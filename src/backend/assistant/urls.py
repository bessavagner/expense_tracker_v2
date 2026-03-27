from django.urls import path

from assistant.views import chat_view, history_view

app_name = "assistant"

urlpatterns = [
    path("chat/", chat_view, name="chat"),
    path("history/", history_view, name="history"),
]
