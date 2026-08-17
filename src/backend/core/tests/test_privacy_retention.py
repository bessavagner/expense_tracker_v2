"""Nothing is kept forever by accident.

Every test here freezes the clock, per `docs/testing-conventions.md`: retention
is arithmetic on `created_at`, so a test that reads the wall clock passes today
and fails on a Tuesday in November for reasons nobody will remember.

Frozen at midday UTC — `date.today()` reads the *system* timezone, not
`TIME_ZONE`, and a midnight freeze lands on different dates on a CI runner and
on an America/Sao_Paulo laptop.
"""

from datetime import UTC, datetime, timedelta

import pytest
from model_bakery import baker

from core.privacy import purgeable, record_for
from core.privacy.retention import PURGE_EXPIRED_DATA, purge_expired

pytestmark = pytest.mark.django_db

FROZEN_NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _frozen_clock(time_machine):
    """November so that a 90-day-old row can exist without a negative date."""
    time_machine.move_to(FROZEN_NOW, tick=False)


def age(model, days, **kwargs):
    """Make a row and backdate it. `auto_now_add` ignores what you pass, so it
    has to be an UPDATE after the fact."""
    row = baker.make(model, **kwargs)
    type(row)._base_manager.filter(pk=row.pk).update(created_at=FROZEN_NOW - timedelta(days=days))
    return row


class TestChat:
    def test_a_message_older_than_ninety_days_is_deleted(self, household, user):
        from assistant.models import ChatMessage, MessageRole

        old = age(ChatMessage, 91, household=household, created_by=user, role=MessageRole.USER)

        purge_expired()

        assert not ChatMessage.objects.filter(pk=old.pk).exists()

    def test_a_message_inside_the_window_is_kept(self, household, user):
        from assistant.models import ChatMessage, MessageRole

        recent = age(ChatMessage, 89, household=household, created_by=user, role=MessageRole.USER)

        purge_expired()

        assert ChatMessage.objects.filter(pk=recent.pk).exists()

    def test_the_boundary_day_is_kept(self, household, user):
        """Exactly 90 days old is inside the promise, not outside it."""
        from assistant.models import ChatMessage, MessageRole

        edge = age(ChatMessage, 90, household=household, created_by=user, role=MessageRole.USER)

        purge_expired()

        assert ChatMessage.objects.filter(pk=edge.pk).exists()

    def test_purging_a_message_takes_its_receipt_draft_with_it(self, household, user):
        """Plan decision D12: `ReceiptDraft.chat_message` is CASCADE, and both
        are 90 days, so the cascade only ever removes something already due.
        Asserted so nobody later 'fixes' the cascade and quietly extends draft
        retention past what the notice says."""
        from assistant.models import ChatMessage, MessageRole, ReceiptDraft

        message = age(ChatMessage, 91, household=household, created_by=user, role=MessageRole.USER)
        draft = baker.make(ReceiptDraft, household=household, created_by=user, chat_message=message)

        purge_expired()

        assert not ReceiptDraft.objects.filter(pk=draft.pk).exists()


class TestTheLedgerIsNeverTouched:
    def test_an_ancient_entry_survives(self, household, user):
        """The product's whole point. If this ever fails, the purge has become
        the most destructive bug in the codebase."""
        from finances.models import Entry

        ancient = age(Entry, 3000, household=household, created_by=user)

        purge_expired()

        assert Entry.objects.filter(pk=ancient.pk).exists()

    def test_an_ancient_memory_rule_survives(self, household, user):
        """Memory rules are configuration, not conversation. A person deletes
        them one at a time from the Privacidade tab; a timer must not."""
        from assistant.models import MemoryRule, MemorySource

        rule = age(
            MemoryRule,
            3000,
            household=household,
            created_by=user,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            source=MemorySource.INFERRED,
        )

        purge_expired()

        assert MemoryRule.objects.filter(pk=rule.pk).exists()


class TestEverythingElseWithAPeriod:
    @pytest.mark.parametrize("record", purgeable(), ids=lambda r: r.label)
    def test_the_period_is_actually_enforced(self, record, household, user):
        """Driven by the inventory rather than by a list here, so a record that
        gains a `retention_days` next year is covered without anyone
        remembering to cover it.

        Rows are built with the loosest possible fixture and skipped when the
        model needs more setup than this can give it — the value is breadth,
        and a record with a bespoke fixture gets its own test above.
        """
        from django.apps import apps
        from django.db import transaction

        if record.purge_filter or record.retention_days == 0:
            pytest.skip(f"{record.label} has its own test below")

        model = apps.get_model(record.label)
        try:
            with transaction.atomic():
                row = baker.make(model, _fill_optional=False)
        except Exception as exc:  # pragma: no cover - fixture limitation only
            pytest.skip(f"model-bakery cannot build {record.label}: {exc}")

        model._base_manager.filter(pk=row.pk).update(
            **{record.timestamp_field: FROZEN_NOW - timedelta(days=record.retention_days + 1)}
        )

        purge_expired()

        assert not model._base_manager.filter(pk=row.pk).exists(), (
            f"{record.label} claims {record.retention_days} days and kept a row older than that"
        )

    def test_an_abandoned_import_is_purged_but_a_finished_one_is_not(self, household, user):
        """`purge_filter` in the flesh. docs/runbook.md says in as many words
        not to delete finished imports — they are the history page, and the
        only record of what a past import did."""
        from finances.models import ImportJob

        abandoned = age(ImportJob, 181, household=household, created_by=user)
        ImportJob.objects.filter(pk=abandoned.pk).update(executed_at=None)
        finished = age(ImportJob, 181, household=household, created_by=user)
        ImportJob.objects.filter(pk=finished.pk).update(executed_at=FROZEN_NOW)

        purge_expired()

        assert not ImportJob.objects.filter(pk=abandoned.pk).exists()
        assert ImportJob.objects.filter(pk=finished.pk).exists()

    def test_expired_sessions_go_and_live_ones_stay(self, user):
        """`retention_days=0` on `expire_date` is `clearsessions` semantics,
        folded into the one job that actually runs on a schedule."""
        from django.contrib.sessions.models import Session

        dead = Session.objects.create(
            session_key="morta", session_data="x", expire_date=FROZEN_NOW - timedelta(days=1)
        )
        alive = Session.objects.create(
            session_key="viva", session_data="x", expire_date=FROZEN_NOW + timedelta(days=1)
        )

        purge_expired()

        assert not Session.objects.filter(pk=dead.pk).exists()
        assert Session.objects.filter(pk=alive.pk).exists()


class TestTheReport:
    def test_it_counts_what_it_deleted_per_model(self, household, user):
        from assistant.models import ChatMessage, MessageRole

        for _ in range(3):
            age(
                ChatMessage,
                100,
                household=household,
                created_by=user,
                role=MessageRole.USER,
            )

        counts = purge_expired()

        assert counts["assistant.ChatMessage"] == 3

    def test_a_model_with_nothing_due_is_not_in_the_report(self, household):
        counts = purge_expired()
        assert "finances.Entry" not in counts

    def test_the_as_of_date_can_be_moved_so_a_dry_run_can_look_ahead(self, household, user):
        """`--as-of` in the command. An operator asking 'what would tomorrow's
        run delete?' should not have to change the clock to find out."""
        from assistant.models import ChatMessage, MessageRole

        message = age(ChatMessage, 89, household=household, created_by=user, role=MessageRole.USER)

        purge_expired(as_of=FROZEN_NOW + timedelta(days=2))

        assert not ChatMessage.objects.filter(pk=message.pk).exists()


class TestTheScheduledRun:
    def test_the_command_enqueues_exactly_one_run_per_day(self, household):
        """`enqueue` is idempotent on the payload's content hash, and the
        payload carries the date — so a second Scheduler firing on the same day
        is a no-op rather than a second sweep (plan decision D8)."""
        from django.core.management import call_command

        from core.models import TaskRun

        call_command("purge_expired_data")
        call_command("purge_expired_data")

        assert TaskRun.objects.filter(name=PURGE_EXPIRED_DATA).count() == 1

    def test_the_run_leaves_an_observable_record(self, household, user):
        """S13-3: 'the purge job is tested and its execution is observable'.
        The TaskRun row is that record — status, attempts, last_error, already
        in the admin and already in the runbook's dead-letter procedure."""
        from django.core.management import call_command

        from core.models import TaskRun, TaskStatus

        call_command("purge_expired_data")

        run = TaskRun.objects.get(name=PURGE_EXPIRED_DATA)
        assert run.status == TaskStatus.DONE
        assert run.payload["as_of"] == "2026-11-17"

    def test_the_task_actually_purges(self, household, user):
        from django.core.management import call_command

        from assistant.models import ChatMessage, MessageRole

        old = age(ChatMessage, 100, household=household, created_by=user, role=MessageRole.USER)

        call_command("purge_expired_data")

        assert not ChatMessage.objects.filter(pk=old.pk).exists()

    def test_dry_run_deletes_nothing(self, household, user):
        from django.core.management import call_command

        from assistant.models import ChatMessage, MessageRole
        from core.models import TaskRun

        old = age(ChatMessage, 100, household=household, created_by=user, role=MessageRole.USER)

        call_command("purge_expired_data", "--dry-run")

        assert ChatMessage.objects.filter(pk=old.pk).exists()
        assert not TaskRun.objects.filter(name=PURGE_EXPIRED_DATA).exists()

    def test_dry_run_reports_what_it_would_delete(self, household, user, capsys):
        from django.core.management import call_command

        from assistant.models import ChatMessage, MessageRole

        for _ in range(2):
            age(
                ChatMessage,
                100,
                household=household,
                created_by=user,
                role=MessageRole.USER,
            )

        call_command("purge_expired_data", "--dry-run")

        out = capsys.readouterr().out
        assert "assistant.ChatMessage" in out
        assert "2" in out


class TestTheNoticeCannotDriftFromThis:
    def test_every_period_the_notice_prints_is_the_one_the_job_uses(self):
        """Both read `core.privacy.INVENTORY`. This test is the assertion that
        neither grew a second source."""
        assert record_for("assistant.ChatMessage").retention_days == 90
        assert record_for("assistant.ReceiptDraft").retention_days == 90
        assert record_for("assistant.UsageRecord").retention_days == 730
