from django.urls import include, path

from finances.views.cockpit import (
    CockpitIncomeCreateView,
    CockpitIncomeDeleteView,
    CockpitIncomeEditModalView,
    CockpitIncomeSectionView,
    CockpitParcelamentoEditModalView,
    CockpitParcelamentosSectionView,
    CockpitSystemicCreateView,
    CockpitSystemicDeleteView,
    CockpitSystemicEditModalView,
    CockpitSystemicPostView,
    CockpitSystemicSectionView,
    CockpitVencimentoSetView,
    CockpitVencimentosSectionView,
)
from finances.views.consolidated import (
    CategoryDetailView,
    ConsolidatedSystemicsView,
    ConsolidatedView,
)
from finances.views.dashboard import DashboardView
from finances.views.entries import (
    EntryCreateView,
    EntryDeleteView,
    EntryEditModalView,
    EntryListView,
    EntryModalView,
    EntryRedirectView,
    EntryUpdateView,
)
from finances.views.importer import (
    ImportExecuteView,
    ImportMappingView,
    ImportPreviewView,
    ImportUploadView,
)
from finances.views.settings import (
    CategoriesTabView,
    CategoryCreateView,
    CategoryDeleteView,
    CategoryEditView,
    IncomeCreateView,
    IncomeGroupDeleteView,
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
    path(
        "entries/<uuid:pk>/edit-modal/",
        EntryEditModalView.as_view(),
        name="entry_edit_modal",
    ),
    # Consolidated
    path("consolidated/", ConsolidatedView.as_view(), name="consolidated"),
    path(
        "consolidated/systemics/",
        ConsolidatedSystemicsView.as_view(),
        name="consolidated_systemics",
    ),
    path(
        "consolidated/detail/<uuid:category_id>/<int:year>/<int:month>/",
        CategoryDetailView.as_view(),
        name="category_detail",
    ),
    # Settings
    path("settings/", SettingsView.as_view(), name="settings"),
    path("settings/income/", IncomeTabView.as_view(), name="settings_income"),
    path("settings/income/create/", IncomeCreateView.as_view(), name="settings_income_create"),
    path(
        "settings/income/group-delete/",
        IncomeGroupDeleteView.as_view(),
        name="settings_income_group_delete",
    ),
    path(
        "settings/income/<uuid:pk>/edit/", IncomeUpdateView.as_view(), name="settings_income_edit"
    ),
    path("settings/systemics/", SystemicsTabView.as_view(), name="settings_systemics"),
    path(
        "settings/systemics/create/", SystemicCreateView.as_view(), name="settings_systemic_create"
    ),
    path(
        "settings/systemics/<uuid:pk>/edit/",
        SystemicEditView.as_view(),
        name="settings_systemic_edit",
    ),
    path(
        "settings/systemics/<uuid:pk>/toggle/",
        SystemicToggleView.as_view(),
        name="settings_systemic_toggle",
    ),
    path(
        "settings/payment-methods/",
        PaymentMethodsTabView.as_view(),
        name="settings_payment_methods",
    ),
    path(
        "settings/payment-methods/create/",
        PaymentMethodCreateView.as_view(),
        name="settings_pm_create",
    ),
    path(
        "settings/payment-methods/<uuid:pk>/edit/",
        PaymentMethodEditView.as_view(),
        name="settings_pm_edit",
    ),
    path(
        "settings/payment-methods/<uuid:pk>/toggle/",
        PaymentMethodToggleView.as_view(),
        name="settings_pm_toggle",
    ),
    path("settings/categories/", CategoriesTabView.as_view(), name="settings_categories"),
    path("settings/categories/create/", CategoryCreateView.as_view(), name="settings_cat_create"),
    path(
        "settings/categories/<uuid:pk>/edit/", CategoryEditView.as_view(), name="settings_cat_edit"
    ),
    path(
        "settings/categories/<uuid:pk>/delete/",
        CategoryDeleteView.as_view(),
        name="settings_cat_delete",
    ),
    # Import
    path("import/", ImportUploadView.as_view(), name="import_upload"),
    path("import/map/", ImportMappingView.as_view(), name="import_map"),
    path("import/preview/", ImportPreviewView.as_view(), name="import_preview"),
    path("import/execute/", ImportExecuteView.as_view(), name="import_execute"),
    # Cockpit — income
    path(
        "cockpit/<int:year>/<int:month>/income/",
        CockpitIncomeSectionView.as_view(),
        name="cockpit_income",
    ),
    path(
        "cockpit/<int:year>/<int:month>/income/create/",
        CockpitIncomeCreateView.as_view(),
        name="cockpit_income_create",
    ),
    path(
        "cockpit/<int:year>/<int:month>/income/<uuid:pk>/delete/",
        CockpitIncomeDeleteView.as_view(),
        name="cockpit_income_delete",
    ),
    path(
        "cockpit/<int:year>/<int:month>/income/<uuid:pk>/edit-modal/",
        CockpitIncomeEditModalView.as_view(),
        name="cockpit_income_edit_modal",
    ),
    # Cockpit — systemics
    path(
        "cockpit/<int:year>/<int:month>/systemic/",
        CockpitSystemicSectionView.as_view(),
        name="cockpit_systemic",
    ),
    path(
        "cockpit/<int:year>/<int:month>/systemic/create/",
        CockpitSystemicCreateView.as_view(),
        name="cockpit_systemic_create",
    ),
    path(
        "cockpit/<int:year>/<int:month>/systemic/<uuid:pk>/post/",
        CockpitSystemicPostView.as_view(),
        name="cockpit_systemic_post",
    ),
    path(
        "cockpit/<int:year>/<int:month>/systemic/<uuid:pk>/delete/",
        CockpitSystemicDeleteView.as_view(),
        name="cockpit_systemic_delete",
    ),
    path(
        "cockpit/<int:year>/<int:month>/systemic/<uuid:pk>/edit-modal/",
        CockpitSystemicEditModalView.as_view(),
        name="cockpit_systemic_edit_modal",
    ),
    # Cockpit — parcelamentos
    path(
        "cockpit/<int:year>/<int:month>/parcelamentos/",
        CockpitParcelamentosSectionView.as_view(),
        name="cockpit_parcelamentos",
    ),
    path(
        "cockpit/<int:year>/<int:month>/parcelamento/<uuid:entry_pk>/edit-modal/",
        CockpitParcelamentoEditModalView.as_view(),
        name="cockpit_parcelamento_edit_modal",
    ),
    # Cockpit — vencimentos
    path(
        "cockpit/<int:year>/<int:month>/vencimentos/",
        CockpitVencimentosSectionView.as_view(),
        name="cockpit_vencimentos",
    ),
    path(
        "cockpit/<int:year>/<int:month>/vencimentos/<uuid:pk>/",
        CockpitVencimentoSetView.as_view(),
        name="cockpit_vencimento_set",
    ),
    # API
    path("api/dashboard/", include("finances.api.urls")),
    # Dashboard (must be last to avoid catching other routes)
    path("", DashboardView.as_view(), name="dashboard"),
]
