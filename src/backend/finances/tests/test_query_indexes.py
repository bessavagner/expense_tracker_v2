"""The hot query predicates must be index-backed, and the indexes must be used.

Two different assertions, deliberately. "The index exists" is a schema fact and
survives a refactor that stops using it; "the planner chose it" is the property
that actually makes a page fast. The second needs enough rows for the planner to
prefer an index, so those tests seed their own.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from model_bakery import baker

from assistant.models import ChatMessage, MessageRole, ReceiptDraft
from finances.models import Entry, Income

EXPECTED_INDEXES = {
    "finances_entry": {"entry_user_billing_type_idx", "entry_user_date_recent_idx"},
    "finances_income": {"income_user_month_idx"},
    "assistant_chatmessage": {"chat_user_recent_idx"},
    "assistant_receiptdraft": {"draft_user_status_recent_idx"},
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
    def bulk_user(self, user):
        category = baker.make("finances.Category", user=user)
        pm = baker.make("finances.PaymentMethod", user=user, type="pix")
        Entry.objects.bulk_create(
            [
                Entry(
                    user=user,
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
                    user=user,
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
                ChatMessage(user=user, role=MessageRole.USER, content=f"m{i}")
                for i in range(self.ROWS)
            ],
            batch_size=500,
        )
        with connection.cursor() as cursor:
            # Without fresh statistics the planner works from defaults and may
            # choose a seq scan on a table it has never seen.
            cursor.execute("ANALYZE finances_entry, finances_income, assistant_chatmessage;")
        return user

    @staticmethod
    def _plan(queryset):
        sql, params = queryset.query.sql_with_params()
        with connection.cursor() as cursor:
            cursor.execute(f"EXPLAIN {sql}", params)  # noqa: S608 — ORM-built SQL
            return "\n".join(row[0] for row in cursor.fetchall())

    def test_entry_billing_month_predicate_uses_an_index(self, bulk_user):
        plan = self._plan(Entry.objects.filter(user=bulk_user, billing_month=date(2026, 3, 1)))
        assert "Seq Scan" not in plan, plan
        assert "entry_user_billing_type_idx" in plan, plan

    def test_entry_type_predicate_uses_the_same_index(self, bulk_user):
        plan = self._plan(
            Entry.objects.filter(
                user=bulk_user, billing_month=date(2026, 3, 1), entry_type="installment"
            )
        )
        assert "Seq Scan" not in plan, plan
        assert "entry_user_billing_type_idx" in plan, plan

    def test_entry_recent_ordering_uses_an_index(self, bulk_user):
        plan = self._plan(Entry.objects.filter(user=bulk_user)[:50])
        assert "Seq Scan" not in plan, plan
        assert "entry_user_date_recent_idx" in plan, plan

    def test_income_month_predicate_uses_an_index(self, bulk_user):
        plan = self._plan(Income.objects.filter(user=bulk_user, month=date(2026, 3, 1)))
        assert "Seq Scan" not in plan, plan
        assert "income_user_month_idx" in plan, plan

    def test_chat_history_load_uses_an_index(self, bulk_user):
        plan = self._plan(ChatMessage.objects.filter(user=bulk_user).order_by("-created_at")[:20])
        assert "Seq Scan" not in plan, plan
        assert "chat_user_recent_idx" in plan, plan


@pytest.mark.django_db
def test_pending_draft_lookup_uses_an_index(user):
    """The lookup ``assistant/views.py:157-161`` runs on every chat turn."""
    ReceiptDraft.objects.bulk_create(
        [ReceiptDraft(user=user, payload={}, status="discarded") for _ in range(3000)],
        batch_size=500,
    )
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE assistant_receiptdraft;")
    queryset = ReceiptDraft.objects.filter(user=user, status="pending").order_by("-created_at")[:1]
    sql, params = queryset.query.sql_with_params()
    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN {sql}", params)  # noqa: S608 — ORM-built SQL
        plan = "\n".join(row[0] for row in cursor.fetchall())
    assert "Seq Scan" not in plan, plan
    assert "draft_user_status_recent_idx" in plan, plan
