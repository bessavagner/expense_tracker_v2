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
from finances.views.settings import (
    CategoriesTabView,
    CategoryCreateView,
    CategoryDeleteView,
    CategoryEditView,
    IncomeCreateView,
    IncomeTabView,
    IncomeUpdateView,
    PaymentMethodCreateView,
    PaymentMethodEditView,
    PaymentMethodsTabView,
    PaymentMethodToggleView,
    SettingsView,
    SystemicCreateView,
    SystemicEditView,
    SystemicsTabView,
    SystemicToggleView,
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
    # Settings
    path("settings/", SettingsView.as_view(), name="settings"),
    path("settings/income/", IncomeTabView.as_view(), name="settings_income"),
    path("settings/income/create/", IncomeCreateView.as_view(), name="settings_income_create"),
    path("settings/income/<uuid:pk>/edit/", IncomeUpdateView.as_view(), name="settings_income_edit"),
    path("settings/systemics/", SystemicsTabView.as_view(), name="settings_systemics"),
    path("settings/systemics/create/", SystemicCreateView.as_view(), name="settings_systemic_create"),
    path("settings/systemics/<uuid:pk>/edit/", SystemicEditView.as_view(), name="settings_systemic_edit"),
    path("settings/systemics/<uuid:pk>/toggle/", SystemicToggleView.as_view(), name="settings_systemic_toggle"),
    path("settings/payment-methods/", PaymentMethodsTabView.as_view(), name="settings_payment_methods"),
    path("settings/payment-methods/create/", PaymentMethodCreateView.as_view(), name="settings_pm_create"),
    path("settings/payment-methods/<uuid:pk>/edit/", PaymentMethodEditView.as_view(), name="settings_pm_edit"),
    path("settings/payment-methods/<uuid:pk>/toggle/", PaymentMethodToggleView.as_view(), name="settings_pm_toggle"),
    path("settings/categories/", CategoriesTabView.as_view(), name="settings_categories"),
    path("settings/categories/create/", CategoryCreateView.as_view(), name="settings_cat_create"),
    path("settings/categories/<uuid:pk>/edit/", CategoryEditView.as_view(), name="settings_cat_edit"),
    path("settings/categories/<uuid:pk>/delete/", CategoryDeleteView.as_view(), name="settings_cat_delete"),
]
