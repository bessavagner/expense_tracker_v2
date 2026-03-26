from django.urls import path

from finances.views.consolidated import (
    CategoryDetailView,
    ConsolidatedSystemicsView,
    ConsolidatedView,
)
from finances.views.entries import (
    EntryCreateView,
    EntryDeleteView,
    EntryListView,
    EntryModalView,
    EntryRedirectView,
    EntryUpdateView,
)

app_name = "finances"

urlpatterns = [
    # Entries
    path("entries/", EntryRedirectView.as_view(), name="entries"),
    path("entries/<int:year>/<int:month>/", EntryListView.as_view(), name="entries_month"),
    path("entries/create/", EntryCreateView.as_view(), name="entry_create"),
    path("entries/<uuid:pk>/edit/", EntryUpdateView.as_view(), name="entry_edit"),
    path("entries/<uuid:pk>/delete/", EntryDeleteView.as_view(), name="entry_delete"),
    path("entries/modal/", EntryModalView.as_view(), name="entry_modal"),
    # Consolidated
    path("consolidated/", ConsolidatedView.as_view(), name="consolidated"),
    path("consolidated/systemics/", ConsolidatedSystemicsView.as_view(), name="consolidated_systemics"),
    path(
        "consolidated/detail/<uuid:category_id>/<int:year>/<int:month>/",
        CategoryDetailView.as_view(),
        name="category_detail",
    ),
]
