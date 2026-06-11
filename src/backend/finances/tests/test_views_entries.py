from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from model_bakery import baker


@pytest.fixture
def logged_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def sample_entries(user):
    category = baker.make("finances.Category", user=user, name="Alimentação")
    pix = baker.make("finances.PaymentMethod", user=user, name="Pix", type="pix")
    entries = [
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, d),
            amount=Decimal("50.00"),
            description=f"Entry {d}",
            category=category,
            payment_method=pix,
            billing_month=date(2026, 3, 1),
        )
        for d in [1, 10, 20]
    ]
    # Entry in different month
    baker.make(
        "finances.Entry",
        user=user,
        date=date(2026, 2, 15),
        amount=Decimal("30.00"),
        description="Feb entry",
        category=category,
        payment_method=pix,
        billing_month=date(2026, 2, 1),
    )
    return entries


@pytest.mark.django_db
class TestEntryListView:
    def test_redirects_to_current_month(self, logged_client):
        response = logged_client.get("/entries/")
        assert response.status_code == 302

    def test_entries_page_renders(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/")
        assert response.status_code == 200
        assert "entries/entries_page.html" in [t.name for t in response.templates]

    def test_htmx_returns_fragment(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        assert "entries/_entries_table.html" in [t.name for t in response.templates]

    def test_filters_by_billing_month(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/")
        entries = response.context["entries"]
        assert len(entries) == 3
        assert all(e.billing_month == date(2026, 3, 1) for e in entries)

    def test_feb_entries_not_in_march(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/")
        entries = response.context["entries"]
        assert not any(e.description == "Feb entry" for e in entries)

    def test_other_user_entries_not_visible(self, logged_client, other_user, sample_entries):
        other_cat = baker.make("finances.Category", user=other_user)
        other_pm = baker.make("finances.PaymentMethod", user=other_user, type="pix")
        baker.make(
            "finances.Entry",
            user=other_user,
            date=date(2026, 3, 5),
            category=other_cat,
            payment_method=other_pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get("/entries/2026/3/")
        entries = response.context["entries"]
        assert len(entries) == 3

    def test_context_has_summary(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/")
        assert "summary" in response.context
        summary = response.context["summary"]
        assert summary["total_expenses"] == Decimal("150.00")
        assert summary["entry_count"] == 3

    def test_context_has_month_tabs(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/")
        assert "months" in response.context
        assert "current_month" in response.context
        assert response.context["current_month"] == 3
        assert response.context["current_year"] == 2026

    def test_unauthenticated_redirects(self):
        client = Client()
        response = client.get("/entries/2026/3/")
        assert response.status_code == 302

    def test_context_has_entry_form(self, logged_client, sample_entries):
        response = logged_client.get("/entries/2026/3/")
        assert "form" in response.context

    def test_only_regular_entries_shown(self, logged_client, user, sample_entries):
        """SYSTEMIC and INSTALLMENT entries must not appear in the Lançamentos list."""
        from finances.models.entry import EntryType

        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        # Create a systemic entry for the same billing month
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 5),
            amount=Decimal("200.00"),
            description="Aluguel sistemático",
            category=category,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
            entry_type=EntryType.SYSTEMIC,
            billing_month_override=True,
        )
        # Create an installment entry for the same billing month
        baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 5),
            amount=Decimal("100.00"),
            description="Notebook parcela",
            category=category,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
            entry_type=EntryType.INSTALLMENT,
            billing_month_override=True,
        )
        response = logged_client.get("/entries/2026/3/")
        entries = response.context["entries"]
        assert all(e.entry_type == EntryType.REGULAR for e in entries)
        assert len(entries) == 3  # only the 3 regular from sample_entries


@pytest.mark.django_db
class TestEntryCreateView:
    def test_create_entry_via_inline(self, logged_client, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        response = logged_client.post(
            "/entries/create/",
            data={
                "date": "2026-03-15",
                "amount": "42.00",
                "description": "Test inline",
                "category": str(category.id),
                "payment_method": str(pm.id),
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        from finances.models import Entry

        assert Entry.objects.filter(user=user, description="Test inline").exists()

    def test_create_entry_invalid_returns_form(self, logged_client, user):
        response = logged_client.post(
            "/entries/create/",
            data={},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        # Should re-render the form with errors


@pytest.mark.django_db
class TestEntryUpdateView:
    def test_get_edit_form(self, logged_client, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        entry = baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 15),
            category=category,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get(f"/entries/{entry.id}/edit/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        assert "entries/_entry_edit_row.html" in [t.name for t in response.templates]

    def test_post_edit_updates_entry(self, logged_client, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        entry = baker.make(
            "finances.Entry",
            user=user,
            date=date(2026, 3, 15),
            amount=Decimal("50.00"),
            description="Old",
            category=category,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.post(
            f"/entries/{entry.id}/edit/",
            data={
                "date": "2026-03-15",
                "amount": "75.00",
                "description": "Updated",
                "category": str(category.id),
                "payment_method": str(pm.id),
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        entry.refresh_from_db()
        assert entry.description == "Updated"
        assert entry.amount == Decimal("75.00")

    def test_cannot_edit_other_user_entry(self, logged_client, other_user):
        category = baker.make("finances.Category", user=other_user)
        pm = baker.make("finances.PaymentMethod", user=other_user, type="pix")
        entry = baker.make(
            "finances.Entry",
            user=other_user,
            category=category,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.get(f"/entries/{entry.id}/edit/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestEntryDeleteView:
    def test_delete_entry(self, logged_client, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        entry = baker.make(
            "finances.Entry",
            user=user,
            category=category,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.delete(f"/entries/{entry.id}/delete/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        from finances.models import Entry

        assert not Entry.objects.filter(id=entry.id).exists()

    def test_cannot_delete_other_user_entry(self, logged_client, other_user):
        category = baker.make("finances.Category", user=other_user)
        pm = baker.make("finances.PaymentMethod", user=other_user, type="pix")
        entry = baker.make(
            "finances.Entry",
            user=other_user,
            category=category,
            payment_method=pm,
            billing_month=date(2026, 3, 1),
        )
        response = logged_client.delete(f"/entries/{entry.id}/delete/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestModalEntryForm:
    def test_get_modal_form(self, logged_client):
        response = logged_client.get("/entries/modal/", HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        assert "partials/_modal_entry_form.html" in [t.name for t in response.templates]

    def test_create_installment_via_modal(self, logged_client, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make(
            "finances.PaymentMethod",
            user=user,
            type="credit_card",
            closing_day=25,
        )
        response = logged_client.post(
            "/entries/modal/",
            data={
                "entry_mode": "installment",
                "date": "2026-03-15",
                "description": "Notebook",
                "category": str(category.id),
                "payment_method": str(pm.id),
                "total_amount": "600.00",
                "num_installments": "3",
                "installment_amount": "200.00",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        from finances.models import Entry, InstallmentPlan

        assert InstallmentPlan.objects.filter(user=user).count() == 1
        assert Entry.objects.filter(user=user, entry_type="installment").count() == 3
