from django.urls import path

from finances.views.entries import EntryListView, EntryRedirectView

app_name = "finances"

urlpatterns = [
    # Entries
    path("entries/", EntryRedirectView.as_view(), name="entries"),
    path("entries/<int:year>/<int:month>/", EntryListView.as_view(), name="entries_month"),
]
