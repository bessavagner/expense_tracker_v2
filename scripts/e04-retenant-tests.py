#!/usr/bin/env python3
"""Rewrite `user=` to `household=` at E04 phase 4's test call sites.

612 call sites across 79 files build a household-owned row and name only the
user. Hand-editing them is 612 chances to typo a fixture name into a silently
empty queryset, so this does it structurally: the AST decides *which* keyword
to touch, and only its exact source span is rewritten, leaving formatting,
comments and every other argument untouched.

Two shapes come out:

    user=user          ->  household=household          (the root conftest fixture)
    user=<anything>    ->  household=household_for_user(<anything>)

`household_for_user` is idempotent and returns the same object the `household`
fixture returns, so the two forms agree by construction — which is why class-
based TestCase modules need no setUp surgery: the inline call works from any
method.

Where the call already passes `household=`, the `user=` keyword is deleted
instead, together with its trailing comma and whitespace.

`AssistantUsageEvent` is never touched: its `user` is the acting member and
survives phase 4. Those call sites are listed for manual handling.

Usage:
    uv run python scripts/e04-retenant-tests.py src/backend/finances/tests/test_entry.py ...
    uv run ruff format <the same paths>
"""

import ast
import sys
from pathlib import Path

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
}
KEEPS_USER = {"AssistantUsageEvent"}

# Expressions that map onto a fixture rather than a lookup. `seeded_user` is
# the `user` fixture with a catalogue attached, so its household is `household`.
FIXTURE_MAP = {
    "user": "household",
    "other_user": "other_household",
    "seeded_user": "household",
}

IMPORT_LINE = "from accounts.resolution import household_for_user\n"


def _model_name(call):
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


def _target_model(call):
    """The household-owned model this call builds, or None."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in {"make", "prepare"}:
        return _model_name(call)
    if isinstance(func, ast.Attribute) and func.attr in {"create", "acreate"}:
        # The whole leading segment, not a prefix: `startswith` would read
        # `PaymentMethodClosingDay.objects` as `PaymentMethod`, and that model
        # deliberately has no household column (epic decision 4).
        owner = ast.unparse(func.value).split(".")[0]
        return owner if owner in HOUSEHOLD_OWNED | KEEPS_USER else None
    if isinstance(func, ast.Name):
        return func.id
    return None


def _offset(lines, lineno, col):
    """Absolute character offset of (1-based lineno, 0-based col)."""
    return sum(len(line) for line in lines[: lineno - 1]) + col


def _span(source, lines, keyword):
    start = _offset(lines, keyword.lineno, keyword.col_offset)
    end = _offset(lines, keyword.value.end_lineno, keyword.value.end_col_offset)
    return start, end


def _eat_trailing_comma(source, end):
    """Extend a deletion span past `, ` or `,\\n    ` so the call still parses."""
    i = end
    while i < len(source) and source[i] in " \t":
        i += 1
    if i < len(source) and source[i] == ",":
        i += 1
        while i < len(source) and source[i] in " \t":
            i += 1
        if i < len(source) and source[i] == "\n":
            i += 1
            while i < len(source) and source[i] in " \t":
                i += 1
    return i


def rewrite(path):
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)

    edits = []  # (start, end, replacement)
    needs_import = False
    manual = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        model = _target_model(node)
        if model is None:
            continue
        user_kw = next((kw for kw in node.keywords if kw.arg == "user"), None)
        if user_kw is None:
            continue
        has_household = any(kw.arg == "household" for kw in node.keywords)

        if model in KEEPS_USER:
            if not has_household:
                manual.append((node.lineno, f"{model}: add household= by hand"))
            continue
        if model not in HOUSEHOLD_OWNED:
            continue

        start, end = _span(source, lines, user_kw)
        if has_household:
            edits.append((start, _eat_trailing_comma(source, end), ""))
            continue

        expression = ast.unparse(user_kw.value)
        if expression in FIXTURE_MAP:
            replacement = f"household={FIXTURE_MAP[expression]}"
        else:
            replacement = f"household=household_for_user({expression})"
            needs_import = True
        edits.append((start, end, replacement))

    if not edits:
        return 0, manual

    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]

    if needs_import and IMPORT_LINE not in source:
        source = _insert_import(source)

    path.write_text(source, encoding="utf-8")
    return len(edits), manual


def _insert_import(source):
    """Put the import after the last existing top-level import line.

    Deliberately crude: `ruff format` and `ruff check --fix` sort and dedupe
    imports afterwards, so getting the position roughly right is enough.
    """
    lines = source.splitlines(keepends=True)
    last = 0
    for i, line in enumerate(lines):
        if line.startswith(("import ", "from ")):
            last = i
    lines.insert(last + 1, IMPORT_LINE)
    return "".join(lines)


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    total = 0
    for raw in argv:
        path = Path(raw)
        count, manual = rewrite(path)
        total += count
        print(f"{count:4d}  {path}")
        for lineno, note in manual:
            print(f"      !! {path}:{lineno} {note}")
    print(f"---- {total} call sites rewritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
