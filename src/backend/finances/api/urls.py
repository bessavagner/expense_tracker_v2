from django.urls import path

from finances.api.views import (
    AlertsView,
    DailyTrendView,
    DiverseSavingsView,
    EvolutionView,
    InstallmentsView,
    ProjectionCardView,
    RecentEntriesView,
    SummaryView,
    TopCategoriesView,
)

urlpatterns = [
    path("summary/", SummaryView.as_view(), name="api_summary"),
    path("top-categories/", TopCategoriesView.as_view(), name="api_top_categories"),
    path("evolution/", EvolutionView.as_view(), name="api_evolution"),
    path("alerts/", AlertsView.as_view(), name="api_alerts"),
    path("recent-entries/", RecentEntriesView.as_view(), name="api_recent_entries"),
    path("installments/", InstallmentsView.as_view(), name="api_installments"),
    path("projection/", ProjectionCardView.as_view(), name="api_projection"),
    path("diverse-savings/", DiverseSavingsView.as_view(), name="api_diverse_savings"),
    path("daily-trend/", DailyTrendView.as_view(), name="api_daily_trend"),
]
