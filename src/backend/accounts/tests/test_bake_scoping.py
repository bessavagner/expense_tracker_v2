"""No test may create a household-owned row without saying which household.

The trap this closes: once `user` is dropped, `household` is a required FK, and
model_bakery satisfies a required FK by *inventing* a related object. A bake
that names no household therefore lands in a brand-new one, `for_household()`
returns nothing, and every "the neighbour's row is absent" assertion passes
because *everything* is absent. Phase 3 hit the same class of bug through
shadowed `logged_client` fixtures; the lesson was to catch it statically.

A ratchet, like `test_scoping_ratchet.py`: BAKE_BASELINE may shrink and never
grow, and Task 16 deletes it once it is empty.
"""

import ast
from pathlib import Path

# tests → accounts → backend → src → repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND = REPO_ROOT / "src" / "backend"

# The concrete models carrying a household column. Spelled out rather than
# discovered because this check parses source, and importing Django's app
# registry to decide what a *string* in someone else's file means would be
# reading the code twice with two different answers.
HOUSEHOLD_OWNED = {
    "Entry",
    "Income",
    "Category",
    "PaymentMethod",
    "Budget",
    "InstallmentPlan",
    "SystemicExpense",
    "ImportBatch",
    "ChatMessage",
    "MemoryRule",
    "ReceiptDraft",
    "MemoryEmbedding",
    "AssistantUsageEvent",
}

BAKE_BASELINE = {
    "src/backend/accounts/tests/test_backfill.py",
    "src/backend/accounts/tests/test_bridge.py",
    "src/backend/assistant/tests/test_analytics.py",
    "src/backend/assistant/tests/test_assistant.py",
    "src/backend/assistant/tests/test_category_memory.py",
    "src/backend/assistant/tests/test_create_entry_fuzzy.py",
    "src/backend/assistant/tests/test_image_extraction_regression.py",
    "src/backend/assistant/tests/test_memory_models.py",
    "src/backend/assistant/tests/test_memory_tools.py",
    "src/backend/assistant/tests/test_models.py",
    "src/backend/assistant/tests/test_receipt_date_and_dup.py",
    "src/backend/assistant/tests/test_receipt_discount_reconcile.py",
    "src/backend/assistant/tests/test_receipt_flow.py",
    "src/backend/assistant/tests/test_receipt_prompts.py",
    "src/backend/assistant/tests/test_semantic_memory.py",
    "src/backend/assistant/tests/test_simulate_projection.py",
    "src/backend/assistant/tests/test_throttling.py",
    "src/backend/assistant/tests/test_tools.py",
    "src/backend/assistant/tests/test_views.py",
    "src/backend/finances/tests/features/test_billing_cycle.py",
    "src/backend/finances/tests/features/test_installments.py",
    "src/backend/finances/tests/features/test_views.py",
    "src/backend/finances/tests/test_api_dashboard.py",
    "src/backend/finances/tests/test_cockpit_income_edit_modal.py",
    "src/backend/finances/tests/test_cockpit_income_views.py",
    "src/backend/finances/tests/test_cockpit_parcelamento_edit_modal.py",
    "src/backend/finances/tests/test_cockpit_parcelamento_manage.py",
    "src/backend/finances/tests/test_cockpit_parcelamentos_views.py",
    "src/backend/finances/tests/test_cockpit_systemic_create.py",
    "src/backend/finances/tests/test_cockpit_systemic_edit_modal.py",
    "src/backend/finances/tests/test_cockpit_systemic_views.py",
    "src/backend/finances/tests/test_cockpit_vencimentos.py",
    "src/backend/finances/tests/test_consolidated_detail_filter.py",
    "src/backend/finances/tests/test_consolidated_dropdown.py",
    "src/backend/finances/tests/test_csrf_htmx.py",
    "src/backend/finances/tests/test_entries_live_summary.py",
    "src/backend/finances/tests/test_entries_pre_origin.py",
    "src/backend/finances/tests/test_entry_edit_modal.py",
    "src/backend/finances/tests/test_entry_mobile_card.py",
    "src/backend/finances/tests/test_forms.py",
    "src/backend/finances/tests/test_hot_path_query_counts.py",
    "src/backend/finances/tests/test_import_double_submit.py",
    "src/backend/finances/tests/test_import_query_count.py",
    "src/backend/finances/tests/test_installment_preview.py",
    "src/backend/finances/tests/test_query_indexes.py",
    "src/backend/finances/tests/test_settings_income_groups.py",
    "src/backend/finances/tests/test_views_consolidated.py",
    "src/backend/finances/tests/test_views_entries.py",
    "src/backend/finances/tests/test_views_importer.py",
    "src/backend/finances/tests/test_views_projection.py",
    "src/backend/finances/tests/test_views_settings.py",
}


def _model_name(call):
    """The model a `baker.make(...)` call targets, or None."""
    if not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value.split(".")[-1]
    if isinstance(first, ast.Name):
        return first.id
    if isinstance(first, ast.Attribute):
        return first.attr
    return None


def _manager_owner(func):
    """The class name in front of `.objects.create(...)`, or None.

    Matched on the whole leading segment rather than by prefix: a `startswith`
    test reads `PaymentMethodClosingDay.objects` as `PaymentMethod`, and that
    model deliberately carries no household column (epic decision 4).
    """
    return ast.unparse(func.value).split(".")[0]


def _violations_in(tree):
    """Calls that build a household-owned row without a `household=` keyword."""
    found = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        keywords = {kw.arg for kw in node.keywords if kw.arg}
        if "household" in keywords:
            continue

        if isinstance(func, ast.Attribute) and func.attr in {"make", "prepare"}:
            if _model_name(node) in HOUSEHOLD_OWNED:
                found += 1
        elif isinstance(func, ast.Attribute) and func.attr in {"create", "acreate"}:
            if _manager_owner(func) in HOUSEHOLD_OWNED:
                found += 1
        elif isinstance(func, ast.Name) and func.id in HOUSEHOLD_OWNED:
            # A bare constructor, e.g. inside a bulk_create list comprehension.
            found += 1
    return found


def _files_baking_without_a_household():
    offenders = set()
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if "/tests/" not in rel and not rel.endswith("conftest.py"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken test file fails elsewhere
            continue
        if _violations_in(tree):
            offenders.add(rel)
    return offenders


def test_no_new_test_bakes_a_row_without_a_household():
    regressions = sorted(_files_baking_without_a_household() - BAKE_BASELINE)
    assert not regressions, (
        "These tests create a household-owned row without saying which "
        "household. model_bakery will invent one, and the assertion will pass "
        f"against an empty queryset: {regressions}"
    )


def test_bake_baseline_has_no_stale_entries():
    stale = sorted(BAKE_BASELINE - _files_baking_without_a_household())
    assert not stale, f"These files are clean — remove them from BAKE_BASELINE: {stale}"
