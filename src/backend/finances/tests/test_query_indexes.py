"""The hot query predicates must be index-backed, and the indexes must be used.

Two different assertions, deliberately. "The index exists" is a schema fact and
survives a refactor that stops using it; "the planner chose it" is the property
that actually makes a page fast. The second needs enough rows for the planner to
prefer an index, so those tests seed their own.

E04 phase 4: every predicate here now leads with `household`, matching the
household-leading twins phase 2 created. This file is converted *before* Task 13
drops the user-leading originals on purpose — if the planner would not choose a
household index, that is worth discovering while the old one still exists.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from model_bakery import baker

from assistant.models import ChatMessage, MessageRole, ReceiptDraft
from finances.models import Entry, Income

EXPECTED_INDEXES = {
    "finances_entry": {"entry_hh_billing_type_idx", "entry_hh_date_recent_idx"},
    "finances_income": {"income_hh_month_idx"},
    "assistant_chatmessage": {"chat_hh_recent_idx"},
    "assistant_receiptdraft": {"draft_hh_status_recent_idx"},
    # The only table keeping a user-leading index past Task 13. The throttle
    # asks "how many turns has this *person* spent" — decision 1 — while E07
    # will ask the household-leading question, so both earn their keep.
    "assistant_usageinteraction": {"usage_hh_kind_recent_idx", "usage_user_kind_recent_idx"},
}


def _index_names(table):
    with connection.cursor() as cursor:
        cursor.execute("SELECT indexname FROM pg_indexes WHERE tablename = %s", [table])
        return {row[0] for row in cursor.fetchall()}


@pytest.mark.django_db
@pytest.mark.parametrize("table,expected", sorted(EXPECTED_INDEXES.items()))
def test_expected_indexes_exist(table, expected):
    assert expected <= _index_names(table), f"{table} is missing {expected - _index_names(table)}"


@pytest.mark.django_db
class TestIndexesAreActuallyUsed:
    """Seed enough rows that a sequential scan is the wrong choice."""

    ROWS = 4000

    @pytest.fixture
    def bulk_household(self, user, household):
        """bulk_create bypasses pre_save, so tenancy is carried in by hand."""
        category = baker.make("finances.Category", household=household)
        pm = baker.make("finances.PaymentMethod", household=household, type="pix")
        Entry.objects.bulk_create(
            [
                Entry(
                    household=household,
                    created_by=user,
                    date=date(2026, 1 + (i % 12), 1 + (i % 28)),
                    amount=Decimal("10.00"),
                    description=f"e{i}",
                    category=category,
                    payment_method=pm,
                    billing_month=date(2026, 1 + (i % 12), 1),
                    billing_month_override=True,
                )
                for i in range(self.ROWS)
            ],
            batch_size=500,
        )
        Income.objects.bulk_create(
            [
                Income(
                    household=household,
                    created_by=user,
                    name=f"i{i}",
                    amount=Decimal("100.00"),
                    month=date(2026, 1 + (i % 12), 1),
                )
                for i in range(self.ROWS)
            ],
            batch_size=500,
        )
        ChatMessage.objects.bulk_create(
            [
                ChatMessage(
                    household=household,
                    created_by=user,
                    role=MessageRole.USER,
                    content=f"m{i}",
                )
                for i in range(self.ROWS)
            ],
            batch_size=500,
        )
        with connection.cursor() as cursor:
            # Without fresh statistics the planner works from defaults and may
            # choose a seq scan on a table it has never seen.
            cursor.execute("ANALYZE finances_entry, finances_income, assistant_chatmessage;")
        return household

    @staticmethod
    def _plan(queryset):
        sql, params = queryset.query.sql_with_params()
        with connection.cursor() as cursor:
            cursor.execute(f"EXPLAIN {sql}", params)  # noqa: S608 — ORM-built SQL
            return "\n".join(row[0] for row in cursor.fetchall())

    def test_entry_billing_month_predicate_uses_an_index(self, bulk_household):
        plan = self._plan(
            Entry.objects.for_household(bulk_household).filter(billing_month=date(2026, 3, 1))
        )
        assert "Seq Scan" not in plan, plan
        assert "entry_hh_billing_type_idx" in plan, plan

    def test_entry_type_predicate_uses_the_same_index(self, bulk_household):
        plan = self._plan(
            Entry.objects.for_household(bulk_household).filter(
                billing_month=date(2026, 3, 1), entry_type="installment"
            )
        )
        assert "Seq Scan" not in plan, plan
        assert "entry_hh_billing_type_idx" in plan, plan

    def test_entry_recent_ordering_uses_an_index(self, bulk_household):
        plan = self._plan(Entry.objects.for_household(bulk_household)[:50])
        assert "Seq Scan" not in plan, plan
        assert "entry_hh_date_recent_idx" in plan, plan

    def test_income_month_predicate_uses_an_index(self, bulk_household):
        plan = self._plan(
            Income.objects.for_household(bulk_household).filter(month=date(2026, 3, 1))
        )
        assert "Seq Scan" not in plan, plan
        assert "income_hh_month_idx" in plan, plan

    def test_chat_history_load_uses_an_index(self, bulk_household):
        plan = self._plan(
            ChatMessage.objects.for_household(bulk_household).order_by("-created_at")[:20]
        )
        assert "Seq Scan" not in plan, plan
        assert "chat_hh_recent_idx" in plan, plan


@pytest.mark.django_db
def test_pending_draft_lookup_uses_an_index(user, household):
    """The lookup ``assistant/views.py`` runs on every chat turn."""
    ReceiptDraft.objects.bulk_create(
        [
            ReceiptDraft(household=household, created_by=user, payload={}, status="discarded")
            for _ in range(3000)
        ],
        batch_size=500,
    )
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE assistant_receiptdraft;")
    queryset = (
        ReceiptDraft.objects.for_household(household)
        .filter(status="pending")
        .order_by("-created_at")[:1]
    )
    sql, params = queryset.query.sql_with_params()
    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN {sql}", params)  # noqa: S608 — ORM-built SQL
        plan = "\n".join(row[0] for row in cursor.fetchall())
    assert "Seq Scan" not in plan, plan
    assert "draft_hh_status_recent_idx" in plan, plan
