from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from model_bakery import baker

from finances.forms import SystemicTemplateEditForm
from finances.models import Entry


@pytest.fixture
def logged_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def template(user):
    cat = baker.make("finances.Category", user=user)
    pm = baker.make("finances.PaymentMethod", user=user, name="C6", type="credit_card")
    return baker.make(
        "finances.SystemicExpense", user=user, name="Spotify - Amanda",
        category=cat, payment_method=pm, default_amount=Decimal("11.90"),
    )


def _data(template, **over):
    d = {
        "name": template.name,
        "category": str(template.category_id),
        "payment_method": str(template.payment_method_id),
        "default_amount": "23.90",
    }
    d.update(over)
    return d


@pytest.mark.django_db
class TestSystemicTemplateEditForm:
    def test_no_recurrence_updates_template_only(self, user, template):
        june = template.create_monthly_entry(date(2026, 6, 1), amount=Decimal("11.90"))

        form = SystemicTemplateEditForm(_data(template), instance=template, user=user)
        assert form.is_valid(), form.errors
        form.save()

        template.refresh_from_db()
        june.refresh_from_db()
        assert template.default_amount == Decimal("23.90")
        assert june.amount == Decimal("11.90")  # month entries untouched

    def test_recurrence_propagates_default_amount(self, user, template):
        june = template.create_monthly_entry(date(2026, 6, 1), amount=Decimal("11.90"))

        form = SystemicTemplateEditForm(
            _data(
                template, is_recurring="on",
                recurrence_start="2026-06-01", recurrence_end="2026-08-01",
            ),
            instance=template, user=user,
        )
        assert form.is_valid(), form.errors
        form.save()

        june.refresh_from_db()
        assert june.amount == Decimal("23.90")
        aug = Entry.objects.get(systemic_expense=template, billing_month=date(2026, 8, 1))
        assert aug.amount == Decimal("23.90")


@pytest.mark.django_db
class TestSystemicSettingsEditViews:
    def test_edit_modal_renders_recurrence_fields(self, logged_client, template):
        r = logged_client.get(
            f"/settings/systemics/{template.id}/edit-modal/", HTTP_HX_REQUEST="true"
        )
        assert r.status_code == 200
        body = r.content.decode()
        assert "Aplicar valor em recorrência" in body
        assert "recurrence_start" in body

    def test_edit_post_with_recurrence_propagates_and_closes_modal(
        self, logged_client, user, template
    ):
        template.create_monthly_entry(date(2026, 6, 1), amount=Decimal("11.90"))

        r = logged_client.post(
            f"/settings/systemics/{template.id}/edit/",
            _data(
                template, is_recurring="on",
                recurrence_start="2026-06-01", recurrence_end="2026-07-01",
            ),
            HTTP_HX_REQUEST="true",
        )
        assert r.status_code == 200
        assert "entry-saved" in r.headers.get("HX-Trigger", "")
        jul = Entry.objects.get(systemic_expense=template, billing_month=date(2026, 7, 1))
        assert jul.amount == Decimal("23.90")
