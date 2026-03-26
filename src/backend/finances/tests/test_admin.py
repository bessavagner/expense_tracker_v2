from django.contrib.admin.sites import AdminSite

from finances.admin import (
    CategoryAdmin,
    EntryAdmin,
    IncomeAdmin,
    InstallmentPlanAdmin,
    PaymentMethodAdmin,
    SystemicExpenseAdmin,
)
from finances.models import (
    Category,
    Entry,
    Income,
    InstallmentPlan,
    PaymentMethod,
    SystemicExpense,
)


class TestAdminRegistration:
    def test_category_admin_registered(self):
        admin = CategoryAdmin(Category, AdminSite())
        assert "name" in admin.list_display
        assert "budget_ceiling" in admin.list_display

    def test_payment_method_admin_registered(self):
        admin = PaymentMethodAdmin(PaymentMethod, AdminSite())
        assert "name" in admin.list_display
        assert "type" in admin.list_display

    def test_entry_admin_registered(self):
        admin = EntryAdmin(Entry, AdminSite())
        assert "date" in admin.list_display
        assert "description" in admin.list_display
        assert "amount" in admin.list_display

    def test_income_admin_registered(self):
        admin = IncomeAdmin(Income, AdminSite())
        assert "name" in admin.list_display

    def test_installment_plan_admin_registered(self):
        admin = InstallmentPlanAdmin(InstallmentPlan, AdminSite())
        assert "description" in admin.list_display

    def test_systemic_expense_admin_registered(self):
        admin = SystemicExpenseAdmin(SystemicExpense, AdminSite())
        assert "name" in admin.list_display
