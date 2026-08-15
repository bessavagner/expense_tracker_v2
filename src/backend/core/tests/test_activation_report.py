"""`activation_report` is E11's evidence that time-to-activation is measurable."""

from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest
from django.core.management import call_command

from core.events import EventName
from core.models import ProductEvent

# Frozen at midday UTC so `--days` window math is exact regardless of when the
# suite runs, rather than drifting relative to the real `timezone.now()`.
FROZEN_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def _event(household, name, at, user=None):
    event = ProductEvent.objects.create(household=household, name=name, user=user, once=True)
    ProductEvent.objects.filter(pk=event.pk).update(created_at=at)
    return event


@pytest.mark.django_db
class TestActivationReport:
    NOW = FROZEN_NOW

    @pytest.fixture(autouse=True)
    def _frozen_clock(self, time_machine):
        time_machine.move_to(self.NOW, tick=False)

    def test_it_reports_zero_without_crashing(self):
        out = StringIO()

        call_command("activation_report", stdout=out)

        assert "Cadastros: 0" in out.getvalue()

    def test_it_counts_signups_and_activations(self, household, other_household, user):
        _event(household, EventName.SIGNUP, self.NOW - timedelta(days=2), user)
        _event(
            household,
            EventName.ACTIVATED,
            self.NOW - timedelta(days=2) + timedelta(hours=1),
            user,
        )
        _event(other_household, EventName.SIGNUP, self.NOW - timedelta(days=1), user)
        out = StringIO()

        call_command("activation_report", stdout=out)

        body = out.getvalue()
        assert "Cadastros: 2" in body
        assert "Ativados: 1" in body
        assert "50.0%" in body

    def test_it_reports_time_to_activation(self, household, user):
        _event(household, EventName.SIGNUP, self.NOW - timedelta(days=1), user)
        _event(
            household,
            EventName.ACTIVATED,
            self.NOW - timedelta(days=1) + timedelta(minutes=30),
            user,
        )
        out = StringIO()

        call_command("activation_report", stdout=out)

        assert "p50" in out.getvalue()
        assert "30" in out.getvalue()

    def test_days_narrows_the_window(self, household, other_household, user):
        _event(household, EventName.SIGNUP, self.NOW - timedelta(days=40), user)
        _event(other_household, EventName.SIGNUP, self.NOW - timedelta(days=1), user)
        out = StringIO()

        call_command("activation_report", "--days", "7", stdout=out)

        assert "Cadastros: 1" in out.getvalue()
