# E07 · Usage Metering & Quota — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every LLM call is recorded against a household with token counts and estimated cost; one function decides quota before any model call; running out of credits degrades to a cheaper tier instead of refusing.

**Architecture:** Two tables at two different grains — `UsageInteraction` (one row per user action, written *before* the call, the credit-accounting unit) and `UsageRecord` (one row per provider call, written *after* it, the cost ledger, with a nullable FK back to its interaction). A single chokepoint `assistant/quota.py::decide()` replaces E01's `assistant/throttling.py`: it evaluates a per-household credit balance to pick a tier (ADVANCED → STANDARD → ESSENTIAL) and a per-user rolling abuse ceiling that can still hard-refuse. Credits are a product currency, not real tokens; real tokens live in `UsageRecord`.

**Tech Stack:** Django 5 (async views), PydanticAI 1.73, PostgreSQL 17 + pgvector, pytest + pytest-django, React 19 island (`ChatWidget.tsx`) built by Vite, uv for Python deps.

**Spec:** [`docs/backlog/E07-usage-metering-and-quota.md`](../../backlog/E07-usage-metering-and-quota.md) — read it first, in full. Its **Decisions taken before planning** section (D1–D5) is binding and must not be re-litigated.

---

## Global Constraints

Copied verbatim from [`docs/backlog/INDEX.md`](../../backlog/INDEX.md) §7. Violating any of these fails review regardless of whether the DoD passes. Every task's requirements implicitly include this section.

1. **TDD.** Test first, always. Project convention, not a preference.
2. **Worktrees.** Feature work happens in an isolated worktree.
3. **The money boundary holds.** The LLM proposes structured intent; **Python computes every number**. No epic may move arithmetic into a prompt.
4. **Tenant scoping is centralized.** After E04, no epic may write `filter(user=...)` on a domain model. Use the household-scoped manager.
5. **Coverage gate.** `coverage report --fail-under=80` must keep passing.
6. **Lint gate.** `ruff check` and `ruff format --check` clean.
7. **No new secret in git.** Env var + Secret Manager, and `.env.example` updated.
8. **pt-BR in the product UI, English in code, comments, and docs.** Existing convention.
9. **Migrations are reversible** or the epic states explicitly why not.
10. **No time-bomb tests.** Any date-sensitive test freezes the clock. See E02.

Plus, specific to this epic:

11. **Never name "the cheapest model" from memory** (spec D3). Before writing any model name or price into code, a `ModelPrice` row, or a document, look up current provider pricing online and record the date checked.
12. **No unscored model swap** (PD-4). ADVANCED and STANDARD both ship pointing at today's `LLM_ASSISTANT_MODEL`. Only ESSENTIAL names a new model, and spec D2 explains why that is not a PD-4 swap.

### Verification commands

```bash
# Full suite — local dev needs the pgvector container on :5433
POSTGRES_PORT=5433 uv run pytest src/backend/ -q

# Coverage gate
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80

# Lint + format
uv run ruff check src/backend/ && uv run ruff format --check src/backend/

# No missing migrations
uv run python src/backend/manage.py makemigrations --check --dry-run
```

---

## Orientation — read this before Task 1

You are working in a Django project at `src/backend/`. Apps: `core` (users, middleware, observability), `accounts` (tenancy: `Household`, `Membership`), `finances` (the ledger), `assistant` (the LLM surface). The React chat widget lives at `src/backend/frontend/src/cards/ChatWidget.tsx`.

**Three things about this codebase that will bite you:**

1. **`chat_view` is a plain async Django view returning `StreamingHttpResponse`.** Not DRF. Not sync. You cannot use DRF throttles, and you cannot call the ORM synchronously inside it — use `acreate` / `acount` / `afirst`, or wrap in `sync_to_async`.
2. **Tenancy is enforced by the database.** `HouseholdOwnedModel` (in `accounts/models.py:72`) gives a non-nullable `household` FK and a `HouseholdScopedManager`. Every new model that belongs to a tenant subclasses it. Never write `.filter(user=...)` on a domain model.
3. **`AgentScope` (`assistant/agents/scope.py`) is a frozen dataclass** carrying `household` and `user` into every agent tool via `RunContext.deps`. It is how you thread anything down into tool bodies. Task 3 adds `interaction` to it.

**Line anchors in this plan were verified at `075b393`.** E06 moved every anchor in the epic's original evidence table by 40–90 lines. If a `sed -n` in a step shows something other than what the step describes, **re-locate by symbol name with grep before editing** — do not trust the number.

### The shape you are building

```
                       chat_view (assistant/views.py)
                                 │
                                 ▼
              quota.decide(household, user, kind) ──► QuotaDecision
                                 │                    .allowed  (False → 429, abuse)
                                 │                    .tier     (ADVANCED|STANDARD|ESSENTIAL)
                                 │                    .degraded (True → tell the user)
                                 ▼
              quota.open_interaction(...) ──► UsageInteraction   ← credits charged here
                                 │                                 (the pre-call row)
                    ┌────────────┼────────────┬──────────────┐
                    ▼            ▼            ▼              ▼
              agent run    extraction    transcription    embedding
                    │            │            │              │
                    └────────────┴────────────┴──────────────┘
                                 ▼
              metering.record_usage(...) ──► UsageRecord  ×N     ← cost computed here
                                                                   (the post-call rows)
```

---

## File Structure

**New files**

| Path | Responsibility |
|---|---|
| `src/backend/core/tiers.py` | The `Tier` enum alone. Lives in `core` because both `accounts` and `assistant` import it, and `accounts → assistant` would be a circular import. |
| `src/backend/assistant/pricing.py` | `ModelPrice` lookup with cache, and USD cost arithmetic from a `RunUsage`. |
| `src/backend/assistant/metering.py` | `record_usage()` — the only writer of `UsageRecord`. Never raises. |
| `src/backend/assistant/quota.py` | **The chokepoint.** `QuotaDecision`, `decide()`, `open_interaction()`, `model_for()`, `balance_for()`. Replaces `assistant/throttling.py`. |
| `src/backend/assistant/management/commands/usage_report.py` | S07-5 operator cost report. |
| `src/backend/assistant/tests/test_pricing.py` | Cost arithmetic and the "every configured model is priced" ratchet. |
| `src/backend/assistant/tests/test_metering.py` | `record_usage` never propagates; correlation; the no-unmetered-call-site ratchet. |
| `src/backend/assistant/tests/test_quota.py` | The chokepoint. **Replaces** `test_throttling.py`. |
| `src/backend/assistant/tests/test_usage_report.py` | Report output. |

**Modified files**

| Path | Change |
|---|---|
| `src/backend/assistant/models.py` | `AssistantUsageEvent`→`UsageInteraction`, `AssistantUsageKind`→`InteractionKind`; new `UsageKind`, `UsageRecord`, `ModelPrice`, `CreditPrice`. |
| `src/backend/accounts/models.py` | New `Plan`; `Household.plan`, `Household.preferred_tier`. |
| `src/backend/assistant/views.py` | `throttle_denial` → chokepoint; thread `interaction` and `model` through every path; meter the agent run. |
| `src/backend/assistant/agents/scope.py` | `AgentScope` gains `interaction`. |
| `src/backend/assistant/agents/extraction.py` | `extract_receipt` meters its run. |
| `src/backend/assistant/services/transcription.py` | Meter each attempt in the fallback loop. |
| `src/backend/assistant/services/embedding.py` | Meter the embedding call. |
| `src/backend/assistant/agents/tools.py` | Pass `ctx.deps` into `get_embedding`. |
| `src/backend/assistant/admin.py` | Register `Plan`, `ModelPrice`, `CreditPrice`. |
| `src/backend/assistant/urls.py` | New `usage/` endpoint. |
| `src/backend/config/settings.py` | Tier→model settings; delete the four `ASSISTANT_THROTTLE_*`. |
| `src/backend/frontend/src/cards/ChatWidget.tsx` | Credit balance, renewal date, tier switcher, degrade notice. |
| `docs/runbook.md` | New §"Usage, credits and cost". |
| `.env.example` | `OPENROUTER_API_KEY`, tier model vars. |

**Deleted files**

| Path | Why |
|---|---|
| `src/backend/assistant/throttling.py` | S07-3: E01's throttle is *replaced*, not layered on. Its rolling-window rules move into `quota.py` as the abuse ceiling. |
| `src/backend/assistant/tests/test_throttling.py` | Superseded by `test_quota.py`. |

---

## Task 1: Rename `AssistantUsageEvent` → `UsageInteraction`

Spec D1. Pure rename, no behaviour change, no data movement. Done first and alone so that if the rename goes wrong you can revert one commit rather than untangle it from new features.

**Files:**
- Modify: `src/backend/assistant/models.py` (`AssistantUsageKind` at :164, `AssistantUsageEvent` at :169)
- Modify: `src/backend/assistant/throttling.py:20,59`
- Modify: `src/backend/assistant/views.py:17-23,175`
- Create: `src/backend/assistant/migrations/0016_rename_usage_interaction.py`
- Modify (string references only): `src/backend/accounts/tests/test_tenancy_bases.py:99`, `src/backend/accounts/tests/test_bake_scoping.py:38`, `src/backend/accounts/tests/test_scoping_ratchet.py:15`, `src/backend/accounts/tests/test_user_column_is_on_its_way_out.py:3,47`, `src/backend/assistant/tests/test_household_columns.py:4,23,33,39`, `src/backend/finances/tests/test_household_indexes.py:4`
- Modify: `src/backend/assistant/tests/test_throttling.py:15,42,43,216,225,304`

**Interfaces:**
- Consumes: nothing.
- Produces: `assistant.models.UsageInteraction` (fields unchanged: `id`, `household`, `user`, `kind`, `created_at`), `assistant.models.InteractionKind` with members `TEXT = "text"` and `IMAGE = "image"` (values unchanged — the DB column keeps its data).

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_usage_interaction_rename.py`:

```python
"""The rename must preserve rows, not just compile.

`RenameModel` is a table rename in Postgres, so data survives by definition —
this test exists so that a future agent who "simplifies" it into a
delete-and-recreate pair is caught immediately.
"""

import pytest
from django.apps import apps

pytestmark = pytest.mark.django_db


def test_the_old_model_name_is_gone():
    with pytest.raises(LookupError):
        apps.get_model("assistant.AssistantUsageEvent")


def test_the_new_model_keeps_every_field():
    model = apps.get_model("assistant.UsageInteraction")
    names = {f.name for f in model._meta.get_fields()}
    assert {"id", "household", "user", "kind", "created_at"} <= names


def test_the_table_name_is_unchanged_so_rows_survive():
    model = apps.get_model("assistant.UsageInteraction")
    assert model._meta.db_table == "assistant_usageinteraction"


def test_kind_values_are_unchanged_so_existing_rows_still_match():
    from assistant.models import InteractionKind

    assert InteractionKind.TEXT == "text"
    assert InteractionKind.IMAGE == "image"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_usage_interaction_rename.py -v
```
Expected: FAIL — `LookupError: App 'assistant' doesn't have a 'UsageInteraction' model.`

- [ ] **Step 3: Rename the model and the enum**

In `src/backend/assistant/models.py`, rename the class `AssistantUsageKind` to `InteractionKind` and `AssistantUsageEvent` to `UsageInteraction`, and replace the docstring — it currently promises the opposite of what spec D1 decided:

```python
class InteractionKind(models.TextChoices):
    TEXT = "text", "Texto"
    IMAGE = "image", "Imagem"


class UsageInteraction(HouseholdOwnedModel):
    """One admitted user action — the unit credits are charged against.

    Written *before* the model call, so the counter records intent to spend
    rather than successful spend: a run that fails halfway still consumed the
    tokens. Audio turns count as ``TEXT``: transcription is roughly two orders
    of magnitude cheaper per turn than a vision call, so only the image path
    earns a budget of its own.

    This is deliberately NOT the cost ledger. One interaction fans out into
    several ``UsageRecord`` rows — a receipt photo costs an extraction, maybe a
    vision retry, and an agent run. The grains are different, which is why E07
    kept two tables (spec D1): a quota decision must happen *before* any call,
    and token counts do not exist until *after* it.

    ``household`` owns the credits; ``user`` is the acting member, which is
    what the per-user abuse ceiling counts (E04 decision 1). Append-only and
    cheap to write.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assistant_usage_events",
    )
    kind = models.CharField(max_length=20, choices=InteractionKind.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "interação com o assistente"
        verbose_name_plural = "interações com o assistente"
        indexes = [
            models.Index(
                fields=["user", "kind", "-created_at"],
                name="usage_user_kind_recent_idx",
            ),
            models.Index(
                fields=["household", "kind", "-created_at"],
                name="usage_hh_kind_recent_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user_id} {self.kind} {self.created_at:%Y-%m-%d %H:%M}"
```

Leave `related_name="assistant_usage_events"` alone — changing it is a separate blast radius for no gain.

- [ ] **Step 4: Update every importer**

```bash
grep -rln "AssistantUsageEvent\|AssistantUsageKind" src/backend --include="*.py"
```

Replace `AssistantUsageEvent` → `UsageInteraction` and `AssistantUsageKind` → `InteractionKind` in every hit, including the quoted label strings `"assistant.AssistantUsageEvent"` → `"assistant.UsageInteraction"` and the bare `"AssistantUsageEvent"` in `accounts/tests/test_bake_scoping.py:38`. Also update the prose in the comments and docstrings at `accounts/tests/test_scoping_ratchet.py:15`, `accounts/tests/test_user_column_is_on_its_way_out.py:3`, `assistant/tests/test_household_columns.py:4`, and `finances/tests/test_household_indexes.py:4` — they name the model in explanatory text.

- [ ] **Step 5: Generate the migration and verify it is a rename, not a drop**

```bash
uv run python src/backend/manage.py makemigrations assistant --name rename_usage_interaction
```

Open the generated file. It **must** contain `migrations.RenameModel(old_name="AssistantUsageEvent", new_name="UsageInteraction")` and must **not** contain `DeleteModel` or `CreateModel`. If Django generated a delete/create pair, discard the file and hand-write it:

```python
from django.db import migrations


class Migration(migrations.Migration):
    """Rename only. Reversible, and no row moves — Postgres renames the table.

    E07 spec D1: `UsageInteraction` and `UsageRecord` are different grains, so
    this table is NOT extended with token counts. It stays the pre-call
    credit-accounting row.
    """

    dependencies = [("assistant", "0015_drop_user")]

    operations = [
        migrations.RenameModel(
            old_name="AssistantUsageEvent",
            new_name="UsageInteraction",
        ),
        migrations.AlterModelOptions(
            name="usageinteraction",
            options={
                "verbose_name": "interação com o assistente",
                "verbose_name_plural": "interações com o assistente",
            },
        ),
    ]
```

- [ ] **Step 6: Rename the test module and run everything**

```bash
git mv src/backend/assistant/tests/test_throttling.py src/backend/assistant/tests/test_quota.py
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
uv run python src/backend/manage.py makemigrations --check --dry-run
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```
Expected: all pass; `makemigrations --check` reports no changes.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(assistant): rename AssistantUsageEvent to UsageInteraction

E07 spec D1: the quota row and the cost row are different grains. This one
stays the pre-call, per-user-action credit unit; UsageRecord (Task 3) becomes
the post-call, per-provider-call cost ledger. RenameModel only — no data moves."
```

---

## Task 2: `ModelPrice` and USD cost arithmetic

Spec D4. The price table is a database model so a price correction never needs a deploy — which matters because spec D3 requires prices to be re-checked online rather than recalled.

**Files:**
- Modify: `src/backend/assistant/models.py`
- Create: `src/backend/assistant/pricing.py`
- Create: `src/backend/assistant/migrations/0017_model_price.py` (generated)
- Create: `src/backend/assistant/migrations/0018_seed_model_prices.py` (hand-written data migration)
- Modify: `src/backend/assistant/admin.py`
- Test: `src/backend/assistant/tests/test_pricing.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `assistant.models.ModelPrice(model_name: str, input_per_mtok: Decimal, output_per_mtok: Decimal, effective_from: date, source_url: str, checked_on: date)`
  - `assistant.pricing.price_for(model_name: str, *, on: date | None = None) -> ModelPrice | None`
  - `assistant.pricing.cost_usd_for(model_name: str, usage) -> Decimal | None` — `usage` is a `pydantic_ai.usage.RunUsage` or any object with `input_tokens` / `output_tokens` ints. Returns `None` when the model has no price row.
  - `assistant.pricing.clear_price_cache() -> None`

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_pricing.py`:

```python
"""Cost arithmetic, and the ratchet that stops a new model metering at zero."""

from datetime import date
from decimal import Decimal

import pytest
from django.conf import settings

from assistant.models import ModelPrice
from assistant.pricing import clear_price_cache, cost_usd_for, price_for

pytestmark = pytest.mark.django_db


class FakeUsage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_price_cache()
    yield
    clear_price_cache()


def _price(name="openai:test", inp="1.00", out="10.00", when=date(2020, 1, 1)):
    return ModelPrice.objects.create(
        model_name=name,
        input_per_mtok=Decimal(inp),
        output_per_mtok=Decimal(out),
        effective_from=when,
        source_url="https://example.test/pricing",
        checked_on=when,
    )


def test_cost_is_tokens_over_a_million_times_the_rate():
    _price(inp="1.00", out="10.00")
    # 500_000 in @ $1/Mtok = $0.50; 200_000 out @ $10/Mtok = $2.00
    assert cost_usd_for("openai:test", FakeUsage(500_000, 200_000)) == Decimal("2.500000")


def test_an_unpriced_model_costs_none_rather_than_zero():
    """Zero would silently understate spend and look like a real measurement."""
    assert cost_usd_for("openai:never-seen", FakeUsage(1000, 1000)) is None


def test_the_most_recent_price_not_after_the_cutoff_wins():
    _price(inp="1.00", out="1.00", when=date(2020, 1, 1))
    _price(inp="2.00", out="2.00", when=date(2026, 1, 1))
    assert price_for("openai:test").input_per_mtok == Decimal("2.00")
    assert price_for("openai:test", on=date(2025, 6, 1)).input_per_mtok == Decimal("1.00")


def test_zero_tokens_costs_zero_not_none():
    _price()
    assert cost_usd_for("openai:test", FakeUsage(0, 0)) == Decimal("0.000000")


def test_missing_token_counts_are_treated_as_zero():
    """A provider that returns no usage must not crash the metering path."""
    _price()
    assert cost_usd_for("openai:test", FakeUsage(None, None)) == Decimal("0.000000")


@pytest.mark.parametrize(
    "setting_name",
    [
        "LLM_MODEL",
        "LLM_ASSISTANT_MODEL",
        "LLM_VISION_MODEL",
        "LLM_TIER_ADVANCED",
        "LLM_TIER_STANDARD",
    ],
)
def test_every_configured_chat_model_has_a_seeded_price(setting_name):
    """The ratchet: adding a model to settings without pricing it fails here.

    Without this, a new model meters at cost=None forever and the operator
    report quietly under-reports. Transcription and embedding models are
    excluded deliberately — see `test_pricing_gaps_are_declared`.
    """
    name = getattr(settings, setting_name, "")
    if not name:
        pytest.skip(f"{setting_name} is not configured")
    assert price_for(name) is not None, (
        f"{setting_name}={name} has no ModelPrice row. Look up current pricing "
        f"online (spec D3 — never from memory) and add it to the seed migration."
    )


def test_pricing_gaps_are_declared():
    """Transcription is priced per MINUTE by the provider, not per token.

    `ModelPrice` models token pricing only, so transcription records carry
    tokens-if-available and cost=None. This is a known, bounded gap: E01
    established that a transcription is ~2 orders of magnitude cheaper than a
    vision call, so it does not move p50/p90/p99. Documented in the runbook.
    This test exists so the gap is a decision, not an oversight.
    """
    assert price_for(settings.LLM_TRANSCRIBE_MODEL) is None
    assert price_for(settings.LLM_TRANSCRIBE_FALLBACK_MODEL) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_pricing.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'assistant.pricing'`

- [ ] **Step 3: Add the model**

Append to `src/backend/assistant/models.py`:

```python
class ModelPrice(models.Model):
    """What a provider charges for one model, per million tokens, in USD.

    A database row rather than a setting (E07 spec D4) because spec D3 requires
    prices to be re-checked against live provider docs rather than recalled —
    and a correction must not need a deploy.

    Not household-scoped: this is global product configuration, not tenant data.

    ``effective_from`` keeps history rather than overwriting: the row that
    applies is the newest one not after the date asked for. Note that a
    ``UsageRecord`` stores its computed cost at write time, so re-pricing never
    rewrites the past — this column exists so a *backfill* can be honest.

    Token pricing only. Transcription models are priced per minute of audio by
    the provider and deliberately have no row here; see the runbook.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_name = models.CharField(
        max_length=120,
        help_text="Exatamente como aparece em settings, incluindo o prefixo do provedor.",
    )
    input_per_mtok = models.DecimalField(max_digits=12, decimal_places=6)
    output_per_mtok = models.DecimalField(max_digits=12, decimal_places=6)
    effective_from = models.DateField()
    source_url = models.URLField(
        max_length=500,
        help_text="A página de preços consultada. Obrigatória: preço sem fonte é palpite.",
    )
    checked_on = models.DateField(help_text="Quando esta linha foi conferida on-line.")

    class Meta:
        verbose_name = "preço de modelo"
        verbose_name_plural = "preços de modelo"
        ordering = ["model_name", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["model_name", "effective_from"],
                name="unique_model_price_per_date",
            )
        ]

    def __str__(self):
        return f"{self.model_name} @ {self.effective_from}"
```

- [ ] **Step 4: Write the pricing service**

Create `src/backend/assistant/pricing.py`:

```python
"""Per-model prices and the USD cost of one provider call.

The cache exists because the quota chokepoint and every metered call site would
otherwise issue a query per call. Prices change a few times a year, so a
process-lifetime cache invalidated on write is the right trade — see
``clear_price_cache``, wired to ``post_save``/``post_delete`` below.
"""

from datetime import date
from decimal import Decimal

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from assistant.models import ModelPrice

MILLION = Decimal(1_000_000)
# Six places: a cheap model at a few hundred tokens costs less than a
# micro-dollar, and rounding those to zero across thousands of calls is how a
# cost report ends up lying.
QUANTUM = Decimal("0.000001")

_cache: dict[tuple[str, date], "ModelPrice | None"] = {}


def clear_price_cache() -> None:
    """Drop the memoised lookups. Called on any ``ModelPrice`` write."""
    _cache.clear()


@receiver(post_save, sender=ModelPrice)
@receiver(post_delete, sender=ModelPrice)
def _invalidate(sender, **kwargs):
    clear_price_cache()


def price_for(model_name: str, *, on: date | None = None) -> ModelPrice | None:
    """The price row in force for ``model_name`` on ``on`` (default: today)."""
    on = on or timezone.localdate()
    key = (model_name, on)
    if key not in _cache:
        _cache[key] = (
            ModelPrice.objects.filter(model_name=model_name, effective_from__lte=on)
            .order_by("-effective_from")
            .first()
        )
    return _cache[key]


def cost_usd_for(model_name: str, usage) -> Decimal | None:
    """USD cost of one call, or ``None`` when the model has no price row.

    ``None`` rather than ``Decimal(0)`` on purpose: zero is indistinguishable
    from a genuinely free call, and an unpriced model silently metering at zero
    is exactly how a cost report becomes fiction. The report counts nulls and
    says so.
    """
    price = price_for(model_name)
    if price is None:
        return None
    inp = Decimal(getattr(usage, "input_tokens", 0) or 0)
    out = Decimal(getattr(usage, "output_tokens", 0) or 0)
    total = (inp / MILLION) * price.input_per_mtok + (out / MILLION) * price.output_per_mtok
    return total.quantize(QUANTUM)
```

- [ ] **Step 5: Look up real prices, then write the seed migration**

**Do this literally — do not skip to writing numbers.** Fetch the current OpenAI pricing page (and OpenRouter's, for Task 4's model) and note the date. Global constraint 11.

```bash
uv run python src/backend/manage.py makemigrations assistant --name model_price
```

Then hand-write `src/backend/assistant/migrations/0018_seed_model_prices.py`, substituting the rates and URLs you just looked up:

```python
"""Seed the price table from prices checked on the date below.

Reversible: the reverse deletes exactly the rows this migration inserted, so
`migrate assistant 0017` is clean.

E07 spec D3: these numbers were read off the provider's live pricing page on
`CHECKED_ON`, not recalled. If you are editing this file, re-read the page.
"""

from datetime import date

from django.db import migrations

CHECKED_ON = date(2026, 8, 14)  # <-- the date you actually looked

# (model_name, input_per_mtok, output_per_mtok, source_url)
PRICES = [
    # <-- fill from the live pricing pages. One row per model named in
    #     settings: LLM_MODEL, LLM_ASSISTANT_MODEL, LLM_VISION_MODEL,
    #     LLM_TIER_ADVANCED, LLM_TIER_STANDARD, LLM_TIER_ESSENTIAL,
    #     LLM_TIER_ESSENTIAL_FALLBACK, and EMBEDDING_MODEL.
    #     A free OpenRouter model gets 0 / 0 and still needs a row, so that
    #     "free" is a recorded fact rather than a missing price.
]


def seed(apps, schema_editor):
    ModelPrice = apps.get_model("assistant", "ModelPrice")
    for name, inp, out, url in PRICES:
        ModelPrice.objects.update_or_create(
            model_name=name,
            effective_from=CHECKED_ON,
            defaults={
                "input_per_mtok": inp,
                "output_per_mtok": out,
                "source_url": url,
                "checked_on": CHECKED_ON,
            },
        )


def unseed(apps, schema_editor):
    ModelPrice = apps.get_model("assistant", "ModelPrice")
    ModelPrice.objects.filter(
        model_name__in=[p[0] for p in PRICES], effective_from=CHECKED_ON
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("assistant", "0017_model_price")]
    operations = [migrations.RunPython(seed, unseed)]
```

> `EMBEDDING_MODEL` is hardcoded at `assistant/services/embedding.py:5`, not a setting. Price it anyway — Task 9 meters it.

- [ ] **Step 6: Register in admin**

Append to `src/backend/assistant/admin.py`:

```python
@admin.register(ModelPrice)
class ModelPriceAdmin(admin.ModelAdmin):
    list_display = (
        "model_name",
        "input_per_mtok",
        "output_per_mtok",
        "effective_from",
        "checked_on",
    )
    list_filter = ("model_name",)
    search_fields = ("model_name",)
```

Add `ModelPrice` to the `from assistant.models import ...` line at the top.

- [ ] **Step 7: Run tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_pricing.py -v
```
Expected: PASS, including `test_every_configured_chat_model_has_a_seeded_price` for `LLM_MODEL`, `LLM_ASSISTANT_MODEL` and `LLM_VISION_MODEL` (the `LLM_TIER_*` params will skip until Task 4 adds those settings).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(assistant): ModelPrice table and USD cost arithmetic

Prices live in the database (E07 spec D4) so a correction needs no deploy,
which matters because spec D3 requires them re-checked online rather than
recalled. Unpriced models cost None, never zero — a silent zero is how a cost
report becomes fiction."
```

---

## Task 3: `UsageRecord` and the metering writer

S07-1. The cost ledger, and the one function that writes it.

**Files:**
- Modify: `src/backend/assistant/models.py`
- Create: `src/backend/assistant/metering.py`
- Modify: `src/backend/assistant/agents/scope.py`
- Create: `src/backend/assistant/migrations/0019_usage_record.py` (generated)
- Test: `src/backend/assistant/tests/test_metering.py`

**Interfaces:**
- Consumes: `UsageInteraction` (Task 1), `cost_usd_for` (Task 2).
- Produces:
  - `assistant.models.UsageKind` — `CHAT = "chat"`, `EXTRACTION = "extraction"`, `TRANSCRIPTION = "transcription"`, `EMBEDDING = "embedding"`
  - `assistant.models.UsageRecord(interaction, household, user, kind, model, input_tokens, output_tokens, cost_usd, latency_ms, ok, created_at)`
  - `async assistant.metering.record_usage(*, household, kind: str, model: str, latency_ms: int, ok: bool, interaction=None, user=None, usage=None) -> None` — never raises.
  - `assistant.metering.Timer` — a context manager exposing `.ms: int`.
  - `AgentScope` gains `interaction: object | None = None`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_metering.py`:

```python
"""The cost ledger. Its cardinal rule: metering never breaks a user's request."""

from decimal import Decimal
from unittest.mock import patch

import pytest

from assistant.metering import Timer, record_usage
from assistant.models import ModelPrice, UsageKind, UsageRecord

pytestmark = pytest.mark.django_db


class FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=50):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


@pytest.fixture
def priced():
    from datetime import date

    ModelPrice.objects.create(
        model_name="openai:test",
        input_per_mtok=Decimal("1.00"),
        output_per_mtok=Decimal("10.00"),
        effective_from=date(2020, 1, 1),
        source_url="https://example.test/pricing",
        checked_on=date(2020, 1, 1),
    )


async def test_a_record_captures_tokens_and_cost(household, user, priced):
    await record_usage(
        household=household,
        user=user,
        kind=UsageKind.CHAT,
        model="openai:test",
        usage=FakeUsage(1_000_000, 100_000),
        latency_ms=1234,
        ok=True,
    )
    rec = await UsageRecord.objects.aget()
    assert rec.input_tokens == 1_000_000
    assert rec.output_tokens == 100_000
    assert rec.cost_usd == Decimal("2.000000")
    assert rec.latency_ms == 1234
    assert rec.ok is True


async def test_a_failed_call_is_still_recorded(household, user, priced):
    """A failed vision call costs money. S07-2."""
    await record_usage(
        household=household,
        user=user,
        kind=UsageKind.EXTRACTION,
        model="openai:test",
        usage=None,
        latency_ms=900,
        ok=False,
    )
    rec = await UsageRecord.objects.aget()
    assert rec.ok is False
    assert rec.input_tokens is None
    assert rec.cost_usd is None


async def test_records_sharing_one_action_are_correlated(household, user, interaction, priced):
    """S07-1: a receipt costing three calls is analysable as one event."""
    for kind in (UsageKind.EXTRACTION, UsageKind.EXTRACTION, UsageKind.CHAT):
        await record_usage(
            interaction=interaction,
            household=household,
            user=user,
            kind=kind,
            model="openai:test",
            usage=FakeUsage(),
            latency_ms=10,
            ok=True,
        )
    count = await UsageRecord.objects.filter(interaction=interaction).acount()
    assert count == 3


async def test_a_metering_failure_never_reaches_the_caller(household, user, priced):
    """S07-1: writing a usage record must never fail the user's request."""
    with patch(
        "assistant.models.UsageRecord.objects.acreate",
        side_effect=RuntimeError("database on fire"),
    ):
        await record_usage(
            household=household,
            user=user,
            kind=UsageKind.CHAT,
            model="openai:test",
            usage=FakeUsage(),
            latency_ms=1,
            ok=True,
        )  # must not raise
    assert await UsageRecord.objects.acount() == 0


async def test_a_metering_failure_is_reported_not_swallowed(household, user, priced):
    """Silent is worse than loud: E06 S06-4 exists because of exactly this."""
    with (
        patch(
            "assistant.models.UsageRecord.objects.acreate",
            side_effect=RuntimeError("database on fire"),
        ),
        patch("assistant.metering.sentry_sdk.capture_exception") as capture,
    ):
        await record_usage(
            household=household,
            user=user,
            kind=UsageKind.CHAT,
            model="openai:test",
            usage=FakeUsage(),
            latency_ms=1,
            ok=True,
        )
    assert capture.called


async def test_an_interactionless_call_is_still_metered(household, priced):
    """An embedding can be triggered outside a chat turn. FK is nullable."""
    await record_usage(
        household=household,
        kind=UsageKind.EMBEDDING,
        model="openai:test",
        usage=FakeUsage(500, 0),
        latency_ms=42,
        ok=True,
    )
    rec = await UsageRecord.objects.aget()
    assert rec.interaction_id is None
    assert rec.user_id is None


def test_timer_reports_elapsed_milliseconds():
    with Timer() as t:
        pass
    assert isinstance(t.ms, int)
    assert t.ms >= 0
```

Add the shared fixtures to `src/backend/assistant/tests/conftest.py` (read the file first — `household` and `user` fixtures may already exist under these or other names; reuse rather than duplicate):

```python
@pytest.fixture
def interaction(db, household, user):
    from assistant.models import InteractionKind, UsageInteraction

    return UsageInteraction.objects.create(
        household=household, user=user, kind=InteractionKind.TEXT
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_metering.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'assistant.metering'`

- [ ] **Step 3: Add the model**

Append to `src/backend/assistant/models.py`:

```python
class UsageKind(models.TextChoices):
    """What kind of provider call this was — NOT what kind of turn it served.

    `InteractionKind` (text/image) describes the user's action. This describes
    one billable call inside it. A single image interaction fans out into
    EXTRACTION, possibly a second EXTRACTION (the vision retry), and a CHAT.
    """

    CHAT = "chat", "Conversa"
    EXTRACTION = "extraction", "Extração de recibo"
    TRANSCRIPTION = "transcription", "Transcrição"
    EMBEDDING = "embedding", "Embedding"


class UsageRecord(HouseholdOwnedModel):
    """One provider call, with what it cost. The cost ledger.

    Written *after* the call, because token counts do not exist before it. That
    is precisely why this is not the same table as ``UsageInteraction``, which
    must be written *before* the call to gate it (E07 spec D1).

    ``interaction`` is nullable: an embedding or a transcription can be
    triggered outside a chat turn, and a record with no interaction is still a
    real cost that must appear in the operator's report.

    ``cost_usd`` is nullable and means "not priceable", never "free". It is
    computed and frozen at write time, so re-pricing a model never rewrites
    history. USD, not BRL: providers price in USD and an FX rate is E15's
    problem, not this table's.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    interaction = models.ForeignKey(
        "assistant.UsageInteraction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="records",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    kind = models.CharField(max_length=20, choices=UsageKind.choices)
    model = models.CharField(max_length=120)
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    latency_ms = models.IntegerField(null=True, blank=True)
    ok = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "registro de uso"
        verbose_name_plural = "registros de uso"
        indexes = [
            # The operator report's access pattern: one household, one period.
            models.Index(
                fields=["household", "-created_at"],
                name="usagerec_hh_recent_idx",
            ),
            # "What does receipt OCR cost relative to text chat?" — S07-5.
            models.Index(fields=["kind", "-created_at"], name="usagerec_kind_recent_idx"),
        ]

    def __str__(self):
        return f"{self.kind} {self.model} {self.cost_usd}"
```

- [ ] **Step 4: Write the metering module**

Create `src/backend/assistant/metering.py`:

```python
"""The only writer of ``UsageRecord``.

One rule governs this module: **metering never fails a user's request.** A
broken cost ledger is an operations problem; a chat turn that 500s because the
cost ledger was broken is a customer problem. So every write is wrapped, and a
failure is reported to Sentry rather than raised (E06 S06-4 — silent is worse
than loud, but loud must not mean broken).
"""

import logging
import time

import sentry_sdk

from assistant.models import UsageRecord
from assistant.pricing import cost_usd_for

logger = logging.getLogger(__name__)


class Timer:
    """Wall-clock milliseconds around a call.

    ``perf_counter`` rather than ``time.time``: latency must not go negative
    because NTP stepped the clock mid-request.
    """

    def __init__(self):
        self.ms = 0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = int((time.perf_counter() - self._start) * 1000)
        return False


async def record_usage(
    *,
    household,
    kind: str,
    model: str,
    latency_ms: int,
    ok: bool,
    interaction=None,
    user=None,
    usage=None,
) -> None:
    """Persist one provider call. Never raises.

    ``usage`` is any object exposing ``input_tokens`` / ``output_tokens`` —
    PydanticAI's ``RunUsage`` is the usual one. ``None`` (a call that failed
    before returning usage) records the attempt with null tokens and null cost,
    because a failed vision call still costs money (S07-2).
    """
    try:
        cost = cost_usd_for(model, usage) if usage is not None else None
        await UsageRecord.objects.acreate(
            interaction=interaction,
            household=household,
            user=user,
            kind=kind,
            model=model,
            input_tokens=getattr(usage, "input_tokens", None) if usage else None,
            output_tokens=getattr(usage, "output_tokens", None) if usage else None,
            cost_usd=cost,
            latency_ms=latency_ms,
            ok=ok,
        )
    except Exception:
        # Deliberately does not re-raise. See the module docstring.
        sentry_sdk.capture_exception()
        logger.warning("Failed to record usage for model=%s kind=%s", model, kind)
```

- [ ] **Step 5: Thread the interaction into `AgentScope`**

Edit `src/backend/assistant/agents/scope.py`:

```python
@dataclass(frozen=True)
class AgentScope:
    """The household a tool may read, and the person on the other end."""

    household: object | None
    user: object
    # The UsageInteraction this run belongs to, so a tool that makes its own
    # provider call (check_memory → get_embedding) can attribute its cost to
    # the same user action. Threaded explicitly rather than via a ContextVar:
    # the SSE generator is iterated by ASGI in a different context from the
    # view that built it, so a ContextVar set in the view would not be visible.
    interaction: object | None = None

    @classmethod
    def for_request(cls, request):
        """Build a scope from a request the middleware has already seen.

        `getattr` rather than `request.household`: a request built without the
        middleware must fail closed to `None` — which every scoped queryset
        turns into `none()` — rather than raise.
        """
        return cls(household=getattr(request, "household", None), user=request.user)
```

- [ ] **Step 6: Migrate and run tests**

```bash
uv run python src/backend/manage.py makemigrations assistant --name usage_record
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_metering.py -v
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(assistant): UsageRecord cost ledger and the metering writer

One row per provider call, correlated to its UsageInteraction by a nullable FK
— S07-1's interaction ID. record_usage never raises: a broken cost ledger must
not break a chat turn. Failed calls are recorded, because a failed vision call
still costs money."
```

---

## Task 4: Tiers, and the ESSENTIAL model

Spec D2 and D3. The tier vocabulary and which model backs each one. No quota logic yet — that is Task 6.

PydanticAI 1.73 supports `openrouter:<model>` natively via `OPENROUTER_API_KEY`; **no new Python dependency is needed.** Verified at `075b393`:

```bash
uv run python -c "from pydantic_ai.models import infer_model; infer_model('openrouter:x/y')"
# UserError: Set the `OPENROUTER_API_KEY` environment variable ... to use the OpenRouter provider.
```

**Files:**
- Create: `src/backend/core/tiers.py`
- Modify: `src/backend/config/settings.py` (LLM block at :331-347)
- Modify: `.env.example`
- Test: `src/backend/core/tests/test_tiers.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `core.tiers.Tier` — `django.db.models.TextChoices` with `ADVANCED = "advanced", "Avançado"`, `STANDARD = "standard", "Padrão"`, `ESSENTIAL = "essential", "Essencial"`
  - `core.tiers.TIER_ORDER: tuple[str, ...]` — `(ADVANCED, STANDARD, ESSENTIAL)`, most expensive first
  - Settings: `LLM_TIER_ADVANCED`, `LLM_TIER_STANDARD`, `LLM_TIER_ESSENTIAL`, `LLM_TIER_ESSENTIAL_FALLBACK`

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_tiers.py`:

```python
"""Tier vocabulary and the settings that back each tier with a model."""

import pytest
from django.conf import settings

from core.tiers import TIER_ORDER, Tier


def test_the_three_tiers_use_the_same_english_word_as_the_product():
    """E07 spec D2: code English == product English. No translation layer."""
    assert Tier.ADVANCED == "advanced"
    assert Tier.STANDARD == "standard"
    assert Tier.ESSENTIAL == "essential"


def test_display_labels_are_pt_br():
    assert Tier.ADVANCED.label == "Avançado"
    assert Tier.STANDARD.label == "Padrão"
    assert Tier.ESSENTIAL.label == "Essencial"


def test_tier_order_runs_most_expensive_first():
    """The cascade walks this list, so its direction is load-bearing."""
    assert TIER_ORDER == (Tier.ADVANCED, Tier.STANDARD, Tier.ESSENTIAL)


def test_advanced_and_standard_ship_pointing_at_todays_model():
    """PD-4: no unscored model swap. E09 owns moving these, with an E08 score."""
    assert settings.LLM_TIER_ADVANCED == settings.LLM_ASSISTANT_MODEL
    assert settings.LLM_TIER_STANDARD == settings.LLM_ASSISTANT_MODEL


def test_essential_falls_back_to_standard_when_unconfigured():
    """Local dev and CI have no OPENROUTER_API_KEY. The app must still work."""
    from assistant.quota import model_for

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "LLM_TIER_ESSENTIAL", "", raising=False)
        assert model_for(Tier.ESSENTIAL) == settings.LLM_TIER_STANDARD
```

> The last test imports `assistant.quota.model_for`, which Task 6 creates. Mark it `@pytest.mark.xfail(reason="model_for lands in Task 6", strict=False)` for now and remove the marker in Task 6, **or** move that single test into `test_quota.py` during Task 6. Either is fine; do not leave a permanently failing test.

- [ ] **Step 2: Run test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_tiers.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'core.tiers'`

- [ ] **Step 3: Create the enum**

Create `src/backend/core/tiers.py`:

```python
"""The three assistant model tiers.

Lives in ``core`` rather than ``assistant`` because both ``accounts``
(``Household.preferred_tier``) and ``assistant`` (``CreditPrice.tier``) need it,
and ``accounts`` importing ``assistant`` would be circular — ``assistant.models``
already imports ``accounts.models.HouseholdOwnedModel``.

The English names are the *product* names (E07 spec D2), so there is no
translation layer between what the code calls a tier and what a customer is
sold. pt-BR labels are the display layer, per global constraint 8.
"""

from django.db import models


class Tier(models.TextChoices):
    ADVANCED = "advanced", "Avançado"
    STANDARD = "standard", "Padrão"
    ESSENTIAL = "essential", "Essencial"


# Most expensive first. The quota cascade walks this in order, so the direction
# is load-bearing, not cosmetic.
TIER_ORDER: tuple[str, ...] = (Tier.ADVANCED, Tier.STANDARD, Tier.ESSENTIAL)
```

- [ ] **Step 4: Add the settings**

In `src/backend/config/settings.py`, immediately after `LLM_VISION_MODEL` (currently line 347):

```python
# Model tiers (E07 spec D2). ADVANCED and STANDARD deliberately ship pointing
# at the SAME model as today: PD-4 forbids a model swap without an E08
# evaluation score, and E09 owns making them different. Shipping them equal
# means the tier machinery is live and provably changes nothing yet.
LLM_TIER_ADVANCED = os.environ.get("LLM_TIER_ADVANCED", LLM_ASSISTANT_MODEL)
LLM_TIER_STANDARD = os.environ.get("LLM_TIER_STANDARD", LLM_ASSISTANT_MODEL)
# ESSENTIAL is where a household lands when its credits run out. Its baseline
# is a 429 and no answer at all, not gpt-5.4 — which is why naming a model here
# is not the unscored swap PD-4 forbids (E07 spec D2).
#
# Free OpenRouter model first, cheapest paid model as the fallback. Empty by
# default so local dev and CI, which have no OPENROUTER_API_KEY, resolve to
# STANDARD instead of failing (see assistant.quota.model_for).
#
# E07 spec D3: DO NOT fill these from memory. Check openrouter.ai/models for
# what is currently free and currently cheapest, and record the date in the
# ModelPrice seed migration.
LLM_TIER_ESSENTIAL = os.environ.get("LLM_TIER_ESSENTIAL", "")
LLM_TIER_ESSENTIAL_FALLBACK = os.environ.get("LLM_TIER_ESSENTIAL_FALLBACK", "")
```

`OPENROUTER_API_KEY` needs no settings entry — PydanticAI reads it from the environment directly, the same way `OPENAI_API_KEY` works today.

- [ ] **Step 5: Update `.env.example`**

Append:

```bash
# Model tiers (E07). ADVANCED/STANDARD default to LLM_ASSISTANT_MODEL.
# ESSENTIAL is the free floor a household degrades to when credits run out.
# Look up the current free and cheapest-paid models at openrouter.ai/models —
# never from memory (E07 spec D3).
LLM_TIER_ADVANCED=
LLM_TIER_STANDARD=
LLM_TIER_ESSENTIAL=
LLM_TIER_ESSENTIAL_FALLBACK=
OPENROUTER_API_KEY=
```

- [ ] **Step 6: Run tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_tiers.py -v
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```
Expected: PASS (with the `model_for` test xfailing).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(core): Tier enum and per-tier model settings

Advanced/Standard/Essential — code English matches product English, pt-BR is
the display layer. ADVANCED and STANDARD both point at today's model so the
tier machinery ships without an unscored swap (PD-4); E09 owns separating them.
PydanticAI 1.73 speaks openrouter:* natively, so ESSENTIAL needs no new dep."
```

---

## Task 5: `Plan`, household credits, and credit prices

S07-4. The credit currency. Balance is **derived**, never stored — no mutable counter, no reset job, no race.

**Files:**
- Modify: `src/backend/accounts/models.py`
- Modify: `src/backend/assistant/models.py`
- Create: `src/backend/accounts/migrations/00XX_plan_and_household_credits.py` (generated)
- Create: `src/backend/assistant/migrations/00XX_credit_price_and_interaction_columns.py` (generated)
- Create: data migration seeding the beta `Plan` and the `CreditPrice` grid
- Modify: `src/backend/assistant/admin.py`
- Test: `src/backend/accounts/tests/test_plans.py`

**Interfaces:**
- Consumes: `Tier`, `TIER_ORDER` (Task 4), `InteractionKind` (Task 1).
- Produces:
  - `accounts.models.Plan(name: str, slug: str, monthly_credits: int, is_default: bool)`
  - `accounts.models.Household.plan` — FK, nullable, `SET_NULL`
  - `accounts.models.Household.preferred_tier` — CharField, `Tier.choices`, default `Tier.ADVANCED`
  - `assistant.models.CreditPrice(tier: str, kind: str, credits: int)`
  - `assistant.models.UsageInteraction.tier` — CharField, `Tier.choices`, default `Tier.ADVANCED`
  - `assistant.models.UsageInteraction.credits_charged` — IntegerField, default 0

- [ ] **Step 1: Write the failing test**

Create `src/backend/accounts/tests/test_plans.py`:

```python
"""Plans, credit grants, and the tier a household prefers."""

import pytest

from accounts.models import Household, Plan
from core.tiers import Tier

pytestmark = pytest.mark.django_db


def test_exactly_one_plan_is_the_default():
    """`balance_for` needs a plan for a household that has none assigned."""
    assert Plan.objects.filter(is_default=True).count() == 1


def test_the_beta_plan_grants_credits():
    plan = Plan.objects.get(is_default=True)
    assert plan.monthly_credits > 0


def test_a_second_default_plan_is_rejected_by_the_database():
    from django.db.utils import IntegrityError

    with pytest.raises(IntegrityError):
        Plan.objects.create(
            name="Outro", slug="outro", monthly_credits=10, is_default=True
        )


def test_a_new_household_prefers_the_advanced_tier():
    hh = Household.objects.create(name="Casa")
    assert hh.preferred_tier == Tier.ADVANCED


def test_a_household_starts_with_no_explicit_plan():
    """Nullable so E15 can assign paid plans without backfilling everyone."""
    hh = Household.objects.create(name="Casa")
    assert hh.plan is None


def test_deleting_a_plan_does_not_delete_households():
    plan = Plan.objects.create(name="Temp", slug="temp", monthly_credits=5)
    hh = Household.objects.create(name="Casa", plan=plan)
    plan.delete()
    hh.refresh_from_db()
    assert hh.plan is None
```

And in `src/backend/assistant/tests/test_quota.py`, replace the file's contents with a first credit-price test (the throttle tests it currently holds are rewritten in Task 6 — for now keep them and append):

```python
def test_essential_costs_zero_credits_for_every_kind():
    """E07 spec D2: ESSENTIAL is the free floor. Charging for it defeats it."""
    from assistant.models import CreditPrice, InteractionKind
    from core.tiers import Tier

    for kind in InteractionKind.values:
        price = CreditPrice.objects.get(tier=Tier.ESSENTIAL, kind=kind)
        assert price.credits == 0


def test_an_image_costs_more_credits_than_text_in_every_paid_tier():
    """A vision call is genuinely more expensive. The currency must say so."""
    from assistant.models import CreditPrice, InteractionKind
    from core.tiers import Tier

    for tier in (Tier.ADVANCED, Tier.STANDARD):
        text = CreditPrice.objects.get(tier=tier, kind=InteractionKind.TEXT).credits
        image = CreditPrice.objects.get(tier=tier, kind=InteractionKind.IMAGE).credits
        assert image > text


def test_advanced_costs_more_credits_than_standard():
    from assistant.models import CreditPrice, InteractionKind
    from core.tiers import Tier

    adv = CreditPrice.objects.get(tier=Tier.ADVANCED, kind=InteractionKind.TEXT).credits
    std = CreditPrice.objects.get(tier=Tier.STANDARD, kind=InteractionKind.TEXT).credits
    assert adv > std
```

- [ ] **Step 2: Run test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_plans.py -v
```
Expected: FAIL — `ImportError: cannot import name 'Plan' from 'accounts.models'`

- [ ] **Step 3: Add `Plan` and the `Household` columns**

In `src/backend/accounts/models.py`, add the import `from core.tiers import Tier` at the top, then insert `Plan` **above** `Household` (Django needs it defined first for the FK), and add two fields to `Household`:

```python
class Plan(models.Model):
    """What a household is entitled to per month.

    Credits are a product currency, deliberately NOT real tokens (E07 spec D2).
    They are a stable unit a customer can reason about and we can reprice
    without changing what they were promised. Real token counts live in
    ``assistant.UsageRecord``.

    E15 extends this with money. Today nothing is charged (PD-3: free capped
    beta, paid at GA), so there is no price column yet.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=40, unique=True)
    monthly_credits = models.PositiveIntegerField(
        help_text="Créditos concedidos no início de cada mês civil."
    )
    # A household with no plan falls back to this one, so `balance_for` never
    # has to decide what "no plan" means. The partial unique constraint below
    # makes "exactly one default" a database fact rather than a convention.
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "plano"
        verbose_name_plural = "planos"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="only_one_default_plan",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.monthly_credits} créditos/mês)"
```

Inside `Household`, after `name`:

```python
    # Nullable: E15 assigns paid plans later without backfilling every beta
    # household. `None` resolves to the default plan at read time.
    plan = models.ForeignKey(
        "accounts.Plan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="households",
    )
    # The tier the household WANTS. The chokepoint may override it downward
    # when credits run out; it never overrides upward (E07 spec D2).
    preferred_tier = models.CharField(
        max_length=20, choices=Tier.choices, default=Tier.ADVANCED
    )
```

- [ ] **Step 4: Add `CreditPrice` and the `UsageInteraction` columns**

In `src/backend/assistant/models.py`, add `from core.tiers import Tier` to the imports, then append:

```python
class CreditPrice(models.Model):
    """How many credits one interaction costs, by tier and kind.

    A database row (E07 spec D4) so the beta's economics can be retuned from
    the admin once Task 10's report shows what things actually cost.

    ESSENTIAL is zero by definition — it is the free floor a household lands on
    when its credits run out, and charging for it would defeat the whole point.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tier = models.CharField(max_length=20, choices=Tier.choices)
    kind = models.CharField(max_length=20, choices=InteractionKind.choices)
    credits = models.PositiveIntegerField()

    class Meta:
        verbose_name = "preço em créditos"
        verbose_name_plural = "preços em créditos"
        ordering = ["tier", "kind"]
        constraints = [
            models.UniqueConstraint(fields=["tier", "kind"], name="unique_credit_price")
        ]

    def __str__(self):
        return f"{self.tier}/{self.kind} = {self.credits}"
```

And add two fields to `UsageInteraction`, after `kind`:

```python
    # Which tier actually served this turn — not which one was asked for. The
    # operator report joins on it, and the UI uses it to tell a degraded user
    # what answered them.
    tier = models.CharField(max_length=20, choices=Tier.choices, default=Tier.ADVANCED)
    # Frozen at write time from CreditPrice, so retuning credit prices never
    # rewrites a household's spent balance. Zero for ESSENTIAL.
    credits_charged = models.PositiveIntegerField(default=0)
```

- [ ] **Step 5: Generate migrations and hand-write the seed**

```bash
uv run python src/backend/manage.py makemigrations accounts --name plan_and_household_credits
uv run python src/backend/manage.py makemigrations assistant --name credit_price_and_interaction_columns
```

Then create a data migration in `accounts` seeding the plan (substitute `MONTHLY_CREDITS` in Task 10 once real data exists — leave the placeholder and the comment):

```python
"""Seed the beta plan.

E07 spec D5: MONTHLY_CREDITS is a PLACEHOLDER. Task 10 of the plan queries the
real ChatMessage/UsageInteraction distribution and replaces it with a number
set generously above the observed p99. Do not ship to users on this value.
"""

from django.db import migrations

SLUG = "beta"
MONTHLY_CREDITS = 5000  # PLACEHOLDER — see the docstring.


def seed(apps, schema_editor):
    Plan = apps.get_model("accounts", "Plan")
    Plan.objects.update_or_create(
        slug=SLUG,
        defaults={"name": "Beta", "monthly_credits": MONTHLY_CREDITS, "is_default": True},
    )


def unseed(apps, schema_editor):
    apps.get_model("accounts", "Plan").objects.filter(slug=SLUG).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "00XX_plan_and_household_credits")]
    operations = [migrations.RunPython(seed, unseed)]
```

And one in `assistant` seeding the credit grid:

```python
"""Seed the credit price grid.

Ratios, not absolutes: the numbers matter only relative to the monthly grant,
which Task 10 sets from real data. A vision call is genuinely far more
expensive than a text turn, and ADVANCED more than STANDARD, so the currency
says so. Task 10's cost report is what justifies retuning these.
"""

from django.db import migrations

# (tier, kind, credits)
GRID = [
    ("advanced", "text", 3),
    ("advanced", "image", 12),
    ("standard", "text", 1),
    ("standard", "image", 4),
    ("essential", "text", 0),
    ("essential", "image", 0),
]


def seed(apps, schema_editor):
    CreditPrice = apps.get_model("assistant", "CreditPrice")
    for tier, kind, credits in GRID:
        CreditPrice.objects.update_or_create(
            tier=tier, kind=kind, defaults={"credits": credits}
        )


def unseed(apps, schema_editor):
    apps.get_model("assistant", "CreditPrice").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("assistant", "00XX_credit_price_and_interaction_columns")]
    operations = [migrations.RunPython(seed, unseed)]
```

- [ ] **Step 6: Register in admin**

Add to `src/backend/assistant/admin.py`:

```python
@admin.register(CreditPrice)
class CreditPriceAdmin(admin.ModelAdmin):
    list_display = ("tier", "kind", "credits")
    list_editable = ("credits",)
    list_filter = ("tier", "kind")
```

And to `src/backend/accounts/admin.py` (create the file if absent, following `assistant/admin.py`'s style):

```python
@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "monthly_credits", "is_default")
    list_editable = ("monthly_credits",)
```

- [ ] **Step 7: Run tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_plans.py src/backend/assistant/tests/test_quota.py -v
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(accounts): Plan, household credits and the credit price grid

Credits are a product currency, not real tokens (E07 spec D2). Balance is
derived from UsageInteraction rows in the current calendar month rather than
stored, so there is no mutable counter, no reset job and no race. The grant is
a documented PLACEHOLDER until Task 10 sets it from real data (spec D5)."
```

---

## Task 6: The chokepoint

S07-3. **The single place a quota decision is made.** `assistant/throttling.py` is deleted here.

Two different refusals, one function: out of credits → *degrade a tier*; over the abuse ceiling → *429*. Keeping the abuse ceiling is what preserves R0's release gate ("an authenticated stranger cannot generate unbounded LLM spend") now that ESSENTIAL has no plan quota.

**Files:**
- Create: `src/backend/assistant/quota.py`
- Delete: `src/backend/assistant/throttling.py`
- Modify: `src/backend/config/settings.py:412-415` (rename the four throttle settings)
- Test: `src/backend/assistant/tests/test_quota.py` (rewrite)

**Interfaces:**
- Consumes: `Tier`, `TIER_ORDER` (Task 4); `Plan`, `Household.plan`, `Household.preferred_tier`, `CreditPrice`, `UsageInteraction.tier`, `UsageInteraction.credits_charged` (Task 5).
- Produces:
  - `assistant.quota.QuotaDecision` — frozen dataclass: `allowed: bool`, `tier: str`, `degraded: bool`, `credits_cost: int`, `remaining: int`, `renews_on: date`, `message: str | None`
  - `async assistant.quota.decide(household, user, kind: str, *, now=None) -> QuotaDecision`
  - `async assistant.quota.open_interaction(decision, household, user, kind) -> UsageInteraction`
  - `async assistant.quota.balance_for(household, *, now=None) -> tuple[int, int, date]` → `(granted, remaining, renews_on)`
  - `assistant.quota.model_for(tier: str) -> str`
  - `assistant.quota.fallback_model_for(tier: str) -> str | None`
  - Settings renamed: `ASSISTANT_ABUSE_TEXT_PER_HOUR`, `ASSISTANT_ABUSE_TEXT_PER_DAY`, `ASSISTANT_ABUSE_IMAGE_PER_HOUR`, `ASSISTANT_ABUSE_IMAGE_PER_DAY`

- [ ] **Step 1: Write the failing test**

Replace `src/backend/assistant/tests/test_quota.py` entirely. Read the old `test_throttling.py` content in git history first (`git show HEAD~5:src/backend/assistant/tests/test_throttling.py`) and **carry over its rolling-window cases** — they still apply to the abuse ceiling and are the R0 regression guard.

```python
"""The single chokepoint. Every quota decision in the product happens here.

Two refusals live in this one function and they are NOT the same thing:

  * out of credits  -> degrade a tier. The user still gets an answer.
  * over the ceiling -> 429. Nothing rescues you. This is R0's guarantee.

Every date-sensitive test freezes the clock (global constraint 10).
"""

from datetime import date, datetime, timedelta, timezone as dt_timezone

import pytest
from django.utils import timezone

from assistant.models import CreditPrice, InteractionKind, UsageInteraction
from assistant.quota import balance_for, decide, model_for, open_interaction
from core.tiers import Tier

pytestmark = pytest.mark.django_db

FROZEN = datetime(2026, 8, 14, 12, 0, tzinfo=dt_timezone.utc)


def _spend(household, user, *, credits, tier=Tier.ADVANCED, kind=InteractionKind.TEXT, at=FROZEN):
    ev = UsageInteraction.objects.create(
        household=household, user=user, kind=kind, tier=tier, credits_charged=credits
    )
    UsageInteraction.objects.filter(pk=ev.pk).update(created_at=at)
    return ev


# --- the credit cascade -------------------------------------------------


async def test_a_fresh_household_gets_its_preferred_tier(household, user):
    d = await decide(household, user, InteractionKind.TEXT, now=FROZEN)
    assert d.allowed is True
    assert d.tier == Tier.ADVANCED
    assert d.degraded is False


async def test_a_household_out_of_credits_is_degraded_not_refused(household, user, plan):
    """E07 spec D2, and the DoD box that says degraded rather than refused."""
    await sync_spend(household, user, credits=plan.monthly_credits)
    d = await decide(household, user, InteractionKind.TEXT, now=FROZEN)
    assert d.allowed is True          # <-- NOT a refusal
    assert d.tier == Tier.ESSENTIAL
    assert d.degraded is True
    assert "Essencial" in d.message


async def test_a_household_that_cannot_afford_advanced_but_can_afford_standard(
    household, user, plan
):
    """One shared pool, spent at different rates — the cascade steps down."""
    adv = await CreditPrice.objects.aget(tier=Tier.ADVANCED, kind=InteractionKind.TEXT)
    std = await CreditPrice.objects.aget(tier=Tier.STANDARD, kind=InteractionKind.TEXT)
    await sync_spend(household, user, credits=plan.monthly_credits - std.credits)
    assert std.credits < adv.credits  # guards the fixture, not the code
    d = await decide(household, user, InteractionKind.TEXT, now=FROZEN)
    assert d.tier == Tier.STANDARD
    assert d.degraded is True


async def test_a_household_that_chose_standard_is_never_upgraded_to_advanced(
    household, user
):
    """The chokepoint overrides downward only. Choosing to save must stick."""
    household.preferred_tier = Tier.STANDARD
    await household.asave()
    d = await decide(household, user, InteractionKind.TEXT, now=FROZEN)
    assert d.tier == Tier.STANDARD
    assert d.degraded is False


async def test_essential_never_runs_out_of_credits(household, user, plan):
    await sync_spend(household, user, credits=plan.monthly_credits * 10)
    d = await decide(household, user, InteractionKind.IMAGE, now=FROZEN)
    assert d.allowed is True
    assert d.tier == Tier.ESSENTIAL
    assert d.credits_cost == 0


async def test_last_months_spend_does_not_count_against_this_month(household, user, plan):
    """Grants are per calendar month. Frozen clock — no time bombs."""
    last_month = FROZEN - timedelta(days=40)
    await sync_spend(household, user, credits=plan.monthly_credits, at=last_month)
    d = await decide(household, user, InteractionKind.TEXT, now=FROZEN)
    assert d.tier == Tier.ADVANCED
    assert d.degraded is False


async def test_balance_reports_grant_remaining_and_renewal(household, user, plan):
    await sync_spend(household, user, credits=100)
    granted, remaining, renews_on = await balance_for(household, now=FROZEN)
    assert granted == plan.monthly_credits
    assert remaining == plan.monthly_credits - 100
    assert renews_on == date(2026, 9, 1)


async def test_a_household_with_no_plan_uses_the_default_plan(household, user, plan):
    household.plan = None
    await household.asave()
    granted, _, _ = await balance_for(household, now=FROZEN)
    assert granted == plan.monthly_credits


# --- the abuse ceiling (R0's guarantee, carried over from E01) -----------


async def test_the_abuse_ceiling_refuses_outright(household, user, settings):
    """Over the ceiling is a 429. No tier rescues you — this is the R0 gate."""
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 2
    for _ in range(2):
        await sync_spend(household, user, credits=0, tier=Tier.ESSENTIAL)
    d = await decide(household, user, InteractionKind.TEXT, now=FROZEN)
    assert d.allowed is False
    assert "hora" in d.message


async def test_the_ceiling_applies_even_on_the_free_tier(household, user, settings, plan):
    """ESSENTIAL has no plan quota. Without this it would be unbounded spend."""
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 2
    await sync_spend(household, user, credits=plan.monthly_credits)  # forces ESSENTIAL
    for _ in range(2):
        await sync_spend(household, user, credits=0, tier=Tier.ESSENTIAL)
    d = await decide(household, user, InteractionKind.TEXT, now=FROZEN)
    assert d.allowed is False


async def test_the_ceiling_is_per_user_not_per_household(household, user, other_user, settings):
    """One member must not be able to lock the other out."""
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 2
    for _ in range(5):
        await sync_spend(household, user, credits=0)
    d = await decide(household, other_user, InteractionKind.TEXT, now=FROZEN)
    assert d.allowed is True


async def test_the_ceiling_window_rolls(household, user, settings):
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 2
    old = FROZEN - timedelta(hours=2)
    for _ in range(5):
        await sync_spend(household, user, credits=0, at=old)
    d = await decide(household, user, InteractionKind.TEXT, now=FROZEN)
    assert d.allowed is True


async def test_the_image_ceiling_is_separate_from_the_text_ceiling(
    household, user, settings
):
    settings.ASSISTANT_ABUSE_IMAGE_PER_HOUR = 1
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 100
    await sync_spend(household, user, credits=0, kind=InteractionKind.IMAGE)
    assert (await decide(household, user, InteractionKind.IMAGE, now=FROZEN)).allowed is False
    assert (await decide(household, user, InteractionKind.TEXT, now=FROZEN)).allowed is True


# --- opening the interaction --------------------------------------------


async def test_open_interaction_freezes_the_tier_and_the_credit_cost(household, user):
    d = await decide(household, user, InteractionKind.TEXT, now=FROZEN)
    ev = await open_interaction(d, household, user, InteractionKind.TEXT)
    assert ev.tier == d.tier
    assert ev.credits_charged == d.credits_cost


# --- model resolution ----------------------------------------------------


def test_essential_falls_back_to_standard_when_unconfigured(settings):
    """CI and local dev have no OPENROUTER_API_KEY. The app must still work."""
    settings.LLM_TIER_ESSENTIAL = ""
    assert model_for(Tier.ESSENTIAL) == settings.LLM_TIER_STANDARD


def test_each_tier_resolves_to_its_configured_model(settings):
    settings.LLM_TIER_ADVANCED = "openai:big"
    settings.LLM_TIER_STANDARD = "openai:mid"
    settings.LLM_TIER_ESSENTIAL = "openrouter:free"
    assert model_for(Tier.ADVANCED) == "openai:big"
    assert model_for(Tier.STANDARD) == "openai:mid"
    assert model_for(Tier.ESSENTIAL) == "openrouter:free"


def test_there_is_exactly_one_enforcement_path():
    """The DoD's grep, as a test so it cannot rot.

    `assistant/throttling.py` is deleted, not deprecated. If this fails,
    someone has added a second place that decides whether a model may be
    called — which is the exact bug S07-3 exists to prevent.
    """
    import pathlib
    import subprocess

    root = pathlib.Path(__file__).resolve().parents[2]
    assert not (root / "assistant" / "throttling.py").exists()
    hits = subprocess.run(
        ["grep", "-rn", "exceeded_rule\\|throttle_denial", str(root), "--include=*.py"],
        capture_output=True,
        text=True,
    ).stdout
    assert hits == "", f"E01's throttle survives somewhere:\n{hits}"
```

Add to `src/backend/assistant/tests/conftest.py`:

```python
@pytest.fixture
def plan(db):
    from accounts.models import Plan

    return Plan.objects.get(is_default=True)


@pytest.fixture
def other_user(db, django_user_model, household):
    """A second member of the same household — the abuse ceiling is per-user."""
    from accounts.models import Membership

    u = django_user_model.objects.create_user(
        username="other", email="other@example.test", password="x"
    )
    Membership.objects.create(user=u, household=household)
    return u
```

And a helper next to the tests, because `_spend` is sync ORM inside async tests:

```python
from asgiref.sync import sync_to_async

sync_spend = sync_to_async(_spend)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_quota.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'assistant.quota'`

- [ ] **Step 3: Rename the throttle settings**

In `src/backend/config/settings.py`, replace lines 412-415:

```python
# The abuse ceiling (E07 S07-3). These were E01's ASSISTANT_THROTTLE_* limits;
# they are renamed, not weakened, because their JOB changed. E01 used them as
# the quota. E07's quota is credits, and these are now purely the anti-abuse
# rail: the thing that keeps R0's release gate true — "an authenticated
# stranger cannot generate unbounded LLM spend" — now that the ESSENTIAL tier
# has no plan quota at all.
#
# Read from settings on every call, so the `settings` fixture can override them
# in tests and an env change takes effect on the next deploy without a code
# change.
ASSISTANT_ABUSE_TEXT_PER_HOUR = int(os.environ.get("ASSISTANT_ABUSE_TEXT_PER_HOUR", "60"))
ASSISTANT_ABUSE_TEXT_PER_DAY = int(os.environ.get("ASSISTANT_ABUSE_TEXT_PER_DAY", "300"))
ASSISTANT_ABUSE_IMAGE_PER_HOUR = int(os.environ.get("ASSISTANT_ABUSE_IMAGE_PER_HOUR", "15"))
ASSISTANT_ABUSE_IMAGE_PER_DAY = int(os.environ.get("ASSISTANT_ABUSE_IMAGE_PER_DAY", "50"))
```

Update `.env.example` and Cloud Run's env vars accordingly — grep for the old names first:

```bash
grep -rn "ASSISTANT_THROTTLE" . --include="*.py" --include="*.md" --include="*.yaml" --include="*.example" --include="*.sh" 2>/dev/null | grep -v node_modules
```

- [ ] **Step 4: Write the chokepoint**

Create `src/backend/assistant/quota.py`:

```python
"""The single place a quota decision is made.

E07 S07-3, and the DoD assertion that `grep` proves no second enforcement path.
`assistant/throttling.py` was E01's version and is deleted, not deprecated —
its rolling-window rules live on here as the abuse ceiling.

TWO refusals live in `decide`, and conflating them is the mistake to avoid:

  * Out of credits  -> DEGRADE. `allowed=True`, a cheaper `tier`,
    `degraded=True`. The user still gets an answer. This is E07 spec D2, and
    it is why the ESSENTIAL tier exists.
  * Over the ceiling -> REFUSE. `allowed=False`. No tier rescues you. This is
    R0's release gate, and it applies on ESSENTIAL too — without it, a tier
    with no plan quota would be unbounded spend.

Why not DRF throttling, and why not middleware: `chat_view` is a plain async
Django view returning a StreamingHttpResponse, and the image budget is tighter
than the text budget, so a middleware would have to parse the multipart body
before the view parses it again. Calling this from `chat_view` keeps the "no
model call before the check" guarantee visible where a reviewer reads it. (Both
reasons are inherited verbatim from E01's throttling.py, and both still hold.)
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from accounts.models import Plan
from assistant.models import CreditPrice, InteractionKind, UsageInteraction
from core.tiers import TIER_ORDER, Tier

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


@dataclass(frozen=True)
class CeilingRule:
    limit: int
    window: timedelta
    label: str  # pt-BR noun for the user-facing message


@dataclass(frozen=True)
class QuotaDecision:
    """What the chokepoint decided. The only input every LLM path needs."""

    allowed: bool
    tier: str
    degraded: bool
    credits_cost: int
    remaining: int
    renews_on: date
    message: str | None = None


def _ceiling_rules(kind: str) -> list[CeilingRule]:
    """Read from settings on every call — see the settings comment."""
    if kind == InteractionKind.IMAGE:
        return [
            CeilingRule(settings.ASSISTANT_ABUSE_IMAGE_PER_HOUR, HOUR, "hora"),
            CeilingRule(settings.ASSISTANT_ABUSE_IMAGE_PER_DAY, DAY, "dia"),
        ]
    return [
        CeilingRule(settings.ASSISTANT_ABUSE_TEXT_PER_HOUR, HOUR, "hora"),
        CeilingRule(settings.ASSISTANT_ABUSE_TEXT_PER_DAY, DAY, "dia"),
    ]


def model_for(tier: str) -> str:
    """The model string PydanticAI should run for ``tier``.

    ESSENTIAL falls back to STANDARD when unconfigured, so local dev and CI —
    which have no OPENROUTER_API_KEY — degrade to a working model rather than
    a crash. A degrade path that itself fails is worse than no degrade path.
    """
    if tier == Tier.ADVANCED:
        return settings.LLM_TIER_ADVANCED
    if tier == Tier.STANDARD:
        return settings.LLM_TIER_STANDARD
    return settings.LLM_TIER_ESSENTIAL or settings.LLM_TIER_STANDARD


def fallback_model_for(tier: str) -> str | None:
    """The second attempt for ``tier``, or ``None`` when there is none.

    Only ESSENTIAL has one: its primary is a free model, and free endpoints
    get rate-limited and deprecated (E07 spec D3).
    """
    if tier == Tier.ESSENTIAL:
        return settings.LLM_TIER_ESSENTIAL_FALLBACK or None
    return None


def _period_bounds(now: datetime) -> tuple[datetime, date]:
    """Start of this calendar month, and the date the grant renews.

    Calendar month, deliberately NOT the domain's `billing_month` — that means
    a credit-card closing cycle in this codebase and reusing the term here
    would be a booby trap for the next reader.
    """
    local = timezone.localtime(now)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    renews = (start + timedelta(days=32)).replace(day=1).date()
    return start, renews


def _balance_sync(household, now: datetime) -> tuple[int, int, date]:
    start, renews = _period_bounds(now)
    plan = household.plan or Plan.objects.filter(is_default=True).first()
    granted = plan.monthly_credits if plan else 0
    spent = (
        UsageInteraction.objects.filter(household=household, created_at__gte=start).aggregate(
            total=Sum("credits_charged")
        )["total"]
        or 0
    )
    return granted, max(0, granted - spent), renews


balance_for_sync = _balance_sync


async def balance_for(household, *, now: datetime | None = None) -> tuple[int, int, date]:
    """``(granted, remaining, renews_on)`` for this calendar month.

    Derived, never stored. There is no balance column, so there is no reset
    job to forget to run, no counter to drift, and no read-modify-write race
    between two members of the same household spending at once.
    """
    return await sync_to_async(_balance_sync)(household, now or timezone.now())


def _credit_costs_sync() -> dict[tuple[str, str], int]:
    return {(p.tier, p.kind): p.credits for p in CreditPrice.objects.all()}


def _ceiling_breach_sync(user, kind: str, now: datetime) -> CeilingRule | None:
    """The first rule this user has already met, or ``None`` when clear.

    "Met", not "exceeded": a user who has spent exactly ``limit`` turns in the
    window is done, because the turn being checked would be number ``limit+1``.
    Counted per USER, not per household — one member must not be able to lock
    the other out (E04 decision 1).
    """
    for rule in _ceiling_rules(kind):
        used = UsageInteraction.objects.filter(
            user=user, kind=kind, created_at__gte=now - rule.window
        ).count()
        if used >= rule.limit:
            return rule
    return None


def _decide_sync(household, user, kind: str, now: datetime) -> QuotaDecision:
    granted, remaining, renews = _balance_sync(household, now)
    costs = _credit_costs_sync()
    preferred = getattr(household, "preferred_tier", Tier.ADVANCED)

    # The cascade: the best tier at or below what they asked for that they can
    # still afford. ESSENTIAL costs zero, so this always terminates.
    start = TIER_ORDER.index(preferred) if preferred in TIER_ORDER else 0
    chosen, cost = Tier.ESSENTIAL, costs.get((Tier.ESSENTIAL, kind), 0)
    for tier in TIER_ORDER[start:]:
        tier_cost = costs.get((tier, kind), 0)
        if tier_cost <= remaining:
            chosen, cost = tier, tier_cost
            break
    degraded = chosen != preferred

    # The abuse ceiling is evaluated LAST and overrides everything, including
    # the free tier. This is the R0 guarantee.
    breach = _ceiling_breach_sync(user, kind, now)
    if breach is not None:
        noun = "fotos" if kind == InteractionKind.IMAGE else "mensagens"
        return QuotaDecision(
            allowed=False,
            tier=chosen,
            degraded=degraded,
            credits_cost=cost,
            remaining=remaining,
            renews_on=renews,
            message=(
                f"Limite de {noun} do assistente atingido "
                f"({breach.limit} por {breach.label}). Tente de novo mais tarde."
            ),
        )

    message = None
    if degraded:
        message = (
            f"Seus créditos do modo {Tier(preferred).label} acabaram. "
            f"Continuo respondendo no modo {Tier(chosen).label} — "
            f"seus créditos renovam em {renews:%d/%m/%Y}."
        )
    return QuotaDecision(
        allowed=True,
        tier=chosen,
        degraded=degraded,
        credits_cost=cost,
        remaining=remaining,
        renews_on=renews,
        message=message,
    )


async def decide(household, user, kind: str, *, now: datetime | None = None) -> QuotaDecision:
    """**The** quota decision. Every LLM path calls this before any model call."""
    return await sync_to_async(_decide_sync)(household, user, kind, now or timezone.now())


async def open_interaction(decision: QuotaDecision, household, user, kind: str):
    """Record the admitted action and charge its credits.

    Written BEFORE the model call, so a request that dies mid-stream still
    counts against the budget it was going to spend. The tier and the credit
    cost are frozen here, so retuning `CreditPrice` never rewrites what a
    household has already spent.
    """
    return await UsageInteraction.objects.acreate(
        household=household,
        user=user,
        kind=kind,
        tier=decision.tier,
        credits_charged=decision.credits_cost,
    )
```

- [ ] **Step 5: Delete E01's throttle**

```bash
git rm src/backend/assistant/throttling.py
```

- [ ] **Step 6: Run tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_quota.py -v
```
Expected: PASS. `src/backend/assistant/views.py` still imports `exceeded_rule` and will fail to import — that is Task 7's job; run only `test_quota.py` here.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(assistant): the quota chokepoint replaces E01's throttle

One function decides. Out of credits degrades a tier and still answers; over
the abuse ceiling refuses outright, on every tier including the free one —
which is what keeps R0's gate true now that ESSENTIAL has no plan quota.
assistant/throttling.py is deleted, and a test greps to keep it deleted."
```

---

## Task 7: Wire the chokepoint into `chat_view`

S07-3's "every LLM path calls it **before** invoking a model", plus threading the chosen tier's model and the interaction through every branch.

**Files:**
- Modify: `src/backend/assistant/views.py` — `throttle_denial` (:162-188), `chat_view` (:196-234), `_sse_response` (:92-159), `_handle_json` (:248), `_handle_multipart` (:270), `_handle_audio` (:298), `_dispatch_extraction` (:339), `_handle_images` (:379)
- Test: `src/backend/assistant/tests/test_views.py` (extend)

**Interfaces:**
- Consumes: `decide`, `open_interaction`, `model_for`, `fallback_model_for`, `QuotaDecision` (Task 6); `AgentScope.interaction` (Task 3).
- Produces: `_sse_response(scope, agent, prompt, *, message_history, user_text=None, model=None, notice=None)` — new `notice` parameter emits a `{"type": "notice", "content": ...}` SSE event before the tokens.

- [ ] **Step 1: Write the failing test**

Append to `src/backend/assistant/tests/test_views.py`:

```python
async def test_an_abuse_refusal_makes_zero_model_calls(async_client, logged_in, settings):
    """DoD: a ceiling-refused request produces zero model calls and zero cost.

    ALLOW_MODEL_REQUESTS=False makes any real model call raise, so reaching one
    fails the test loudly rather than costing money.
    """
    from pydantic_ai import models

    from assistant.models import UsageRecord

    models.ALLOW_MODEL_REQUESTS = False
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 0
    resp = await async_client.post(
        "/assistant/chat/",
        data={"message": "oi"},
        content_type="application/json",
    )
    assert resp.status_code == 429
    assert await UsageRecord.objects.acount() == 0


async def test_a_household_out_of_credits_still_gets_an_answer(
    async_client, logged_in, household, plan
):
    """DoD: zero credits degrades to ESSENTIAL, it does NOT refuse."""
    from assistant.models import InteractionKind, UsageInteraction
    from core.tiers import Tier

    await UsageInteraction.objects.acreate(
        household=household,
        user=logged_in,
        kind=InteractionKind.TEXT,
        tier=Tier.ADVANCED,
        credits_charged=plan.monthly_credits,
    )
    with capture_run_messages_stub():  # your existing agent-override helper
        resp = await async_client.post(
            "/assistant/chat/",
            data={"message": "oi"},
            content_type="application/json",
        )
    assert resp.status_code == 200
    body = b"".join([chunk async for chunk in resp.streaming_content]).decode()
    assert "Essencial" in body

    ev = await UsageInteraction.objects.filter(tier=Tier.ESSENTIAL).afirst()
    assert ev is not None
    assert ev.credits_charged == 0


async def test_the_interaction_is_opened_before_any_model_call(
    async_client, logged_in, household
):
    """A stream that dies mid-flight must still have counted against budget."""
    from assistant.models import UsageInteraction

    # Force the agent run to explode. The interaction row must exist anyway.
    with agent_raises_stub(RuntimeError("provider down")):
        await async_client.post(
            "/assistant/chat/",
            data={"message": "oi"},
            content_type="application/json",
        )
    assert await UsageInteraction.objects.acount() == 1
```

> `capture_run_messages_stub` / `agent_raises_stub` are placeholders for the
> agent-override helpers this suite already uses. **Read
> `src/backend/assistant/tests/test_views.py` and `conftest.py` first** and use
> the existing mechanism (`assistant_agent.override(model=TestModel(...))` or
> `FunctionModel`) rather than inventing a new one.

- [ ] **Step 2: Run test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_views.py -v -k "abuse or credits or before_any_model"
```
Expected: FAIL — `ImportError: cannot import name 'exceeded_rule' from 'assistant.throttling'` (the module is gone).

- [ ] **Step 3: Replace `throttle_denial` with the chokepoint**

In `src/backend/assistant/views.py`, change the imports (currently :17-26):

```python
from assistant.models import ChatMessage, InteractionKind, MessageRole, ReceiptDraft
from assistant.quota import decide, fallback_model_for, model_for, open_interaction
from assistant.services.image_prep import prepare_receipt_image
from assistant.services.transcription import transcribe_audio
```

Delete `throttle_denial` entirely (:162-188) and rewrite `chat_view`'s gate (:228-234):

```python
    denial_or_decision = await decide(scope.household, user, kind)
    if not denial_or_decision.allowed:
        return JsonResponse({"error": denial_or_decision.message}, status=429)

    # Opened BEFORE any model call, so a request that dies mid-stream still
    # counts against the budget it was going to spend. Re-bind the scope so
    # every downstream tool can attribute its own provider calls to this
    # interaction (see AgentScope.interaction).
    interaction = await open_interaction(denial_or_decision, scope.household, user, kind)
    scope = AgentScope(household=scope.household, user=user, interaction=interaction)

    if is_multipart:
        return await _handle_multipart(request, scope, denial_or_decision)
    return await _handle_json(request, scope, denial_or_decision)
```

- [ ] **Step 4: Thread the decision through every branch**

Add a `decision` parameter to `_handle_json`, `_handle_multipart`, `_handle_audio`, `_handle_images` and `_dispatch_extraction`, and pass it to every `_sse_response` call. In `_sse_response`, add the `notice` parameter and resolve the model:

```python
def _sse_response(
    scope,
    agent,
    prompt,
    *,
    message_history,
    user_text=None,
    model=None,
    notice=None,
):
    """Monta a StreamingHttpResponse SSE para qualquer agente/prompt.

    ``notice`` emite um evento ``notice`` antes dos tokens — usado para avisar
    que os créditos acabaram e a resposta veio do modo Essencial (E07 S07-4:
    a degradação é visível, nunca silenciosa).

    ``model`` faz override por execução do modelo do agente (usado no fluxo de
    foto para ler o recibo, e pelo tier escolhido pelo chokepoint). Em testes,
    ``agent.override(model=...)`` tem precedência sobre este argumento.
    """

    async def stream_response():
        if notice:
            yield json.dumps({"type": "notice", "content": notice}, ensure_ascii=False) + "\n"
        if user_text:
            yield json.dumps({"type": "user_text", "content": user_text}, ensure_ascii=False) + "\n"
        ...
```

Every call site becomes, e.g. in `_handle_json`:

```python
    return _sse_response(
        scope,
        assistant_agent,
        message,
        message_history=history,
        model=model_for(decision.tier),
        notice=decision.message,
    )
```

Apply the same `model=` / `notice=` pair to the four other `_sse_response` calls (in `_handle_multipart` ×2, `_handle_audio` ×2, `_dispatch_extraction` ×2). The `_resend()` generator in `_handle_images` makes no model call and needs neither.

- [ ] **Step 5: Add the ESSENTIAL fallback retry**

Inside `stream_response`, the existing `except Exception:` block (:125-133) becomes a single retry when nothing has been streamed yet:

```python
        except Exception:
            sentry_sdk.capture_exception()
            fallback = fallback_model_for(getattr(scope, "tier", None)) if False else None
            # Retry ONLY when nothing reached the user yet. A free-tier endpoint
            # that dies after ten tokens cannot be replayed — the client already
            # rendered them — so a mid-stream failure stays a failure.
            ...
```

**Simpler and correct:** pass the resolved fallback in explicitly rather than deriving it inside the generator. Add a `fallback_model=None` parameter to `_sse_response`, set it at each call site from `fallback_model_for(decision.tier)`, and:

```python
        full_response = ""
        data_changed = False
        attempts = [model] + ([fallback_model] if fallback_model else [])
        for attempt, attempt_model in enumerate(attempts):
            try:
                async with agent.run_stream(
                    prompt, deps=scope, message_history=message_history, model=attempt_model
                ) as stream:
                    async for text in stream.stream_text(delta=True):
                        full_response += text
                        yield json.dumps(
                            {"type": "token", "content": text}, ensure_ascii=False
                        ) + "\n"
                    try:
                        data_changed = _run_mutated_data(stream.all_messages())
                    except Exception:
                        sentry_sdk.capture_exception()
                        data_changed = False
                break
            except Exception:
                sentry_sdk.capture_exception()
                # Only the first attempt may be retried, and only if nothing
                # reached the user: a free endpoint that dies after ten tokens
                # cannot be replayed — the client already rendered them.
                if attempt + 1 < len(attempts) and not full_response:
                    continue
                error_msg = "Erro ao processar mensagem. Tente novamente."
                yield json.dumps(
                    {"type": "error", "content": error_msg}, ensure_ascii=False
                ) + "\n"
                full_response = error_msg
                break
```

- [ ] **Step 6: Run tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/ -q
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(assistant): chat_view decides quota at the chokepoint

Every path resolves its model from the tier the chokepoint chose, and the
interaction is opened before any model call so a stream that dies mid-flight
still counts. A degrade is announced to the user as an SSE notice, never
applied silently. The free tier gets one fallback retry, but only when nothing
has reached the client yet."
```

---

## Task 8: Meter the chat agent run

S07-2, for the largest call site.

**Files:**
- Modify: `src/backend/assistant/views.py` (`_sse_response`)
- Test: `src/backend/assistant/tests/test_metering.py` (extend)

**Interfaces:**
- Consumes: `record_usage`, `Timer`, `UsageKind` (Task 3).
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

Append to `src/backend/assistant/tests/test_metering.py`:

```python
async def test_a_chat_turn_produces_one_usage_record(async_client, logged_in, priced):
    from assistant.models import UsageKind, UsageRecord

    with agent_override_stub():  # existing helper; see test_views.py
        resp = await async_client.post(
            "/assistant/chat/",
            data={"message": "oi"},
            content_type="application/json",
        )
        [chunk async for chunk in resp.streaming_content]  # drain the stream

    rec = await UsageRecord.objects.aget()
    assert rec.kind == UsageKind.CHAT
    assert rec.interaction_id is not None
    assert rec.latency_ms is not None


async def test_a_failed_chat_run_is_still_recorded(async_client, logged_in, priced):
    from assistant.models import UsageRecord

    with agent_raises_stub(RuntimeError("provider down")):
        resp = await async_client.post(
            "/assistant/chat/",
            data={"message": "oi"},
            content_type="application/json",
        )
        [chunk async for chunk in resp.streaming_content]

    rec = await UsageRecord.objects.aget()
    assert rec.ok is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_metering.py -v -k chat
```
Expected: FAIL — `UsageRecord.DoesNotExist`

- [ ] **Step 3: Meter inside `stream_response`**

`stream.usage()` is only complete after the stream finishes — PydanticAI documents this explicitly. So record after the `async for` drains, inside the same `async with`:

```python
        for attempt, attempt_model in enumerate(attempts):
            timer = Timer()
            try:
                with timer:
                    async with agent.run_stream(
                        prompt, deps=scope, message_history=message_history, model=attempt_model
                    ) as stream:
                        async for text in stream.stream_text(delta=True):
                            full_response += text
                            yield json.dumps(
                                {"type": "token", "content": text}, ensure_ascii=False
                            ) + "\n"
                        # usage() is only complete once the stream is drained.
                        run_usage = stream.usage()
                        try:
                            data_changed = _run_mutated_data(stream.all_messages())
                        except Exception:
                            sentry_sdk.capture_exception()
                            data_changed = False
                await record_usage(
                    interaction=getattr(scope, "interaction", None),
                    household=scope.household,
                    user=scope.user,
                    kind=UsageKind.CHAT,
                    model=attempt_model,
                    usage=run_usage,
                    latency_ms=timer.ms,
                    ok=True,
                )
                break
            except Exception:
                sentry_sdk.capture_exception()
                await record_usage(
                    interaction=getattr(scope, "interaction", None),
                    household=scope.household,
                    user=scope.user,
                    kind=UsageKind.CHAT,
                    model=attempt_model,
                    usage=None,
                    latency_ms=timer.ms,
                    ok=False,
                )
                if attempt + 1 < len(attempts) and not full_response:
                    continue
                error_msg = "Erro ao processar mensagem. Tente novamente."
                yield json.dumps(
                    {"type": "error", "content": error_msg}, ensure_ascii=False
                ) + "\n"
                full_response = error_msg
                break
```

Add to the imports at the top of `views.py`:

```python
from assistant.metering import Timer, record_usage
from assistant.models import UsageKind
```

- [ ] **Step 4: Run tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/ -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(assistant): meter the chat agent run

stream.usage() only completes once the stream drains, so the record is written
inside the async with, after the async for. A failed run is recorded too —
tokens the provider consumed before dying are still billed."
```

---

## Task 9: Meter extraction, transcription and embeddings — and ratchet it

S07-2 in full, including the DoD's "proven by a test that fails if a new unmetered call site is added".

**Files:**
- Modify: `src/backend/assistant/agents/extraction.py` (`extract_receipt` at :166-196)
- Modify: `src/backend/assistant/services/transcription.py` (the loop at :55-71)
- Modify: `src/backend/assistant/services/embedding.py`
- Modify: `src/backend/assistant/agents/tools.py:1224`
- Modify: `src/backend/assistant/views.py` (`_handle_images` :426,438; `_handle_audio` :307)
- Test: `src/backend/assistant/tests/test_metering.py` (extend)

**Interfaces:**
- Consumes: `record_usage`, `Timer`, `UsageKind`.
- Produces:
  - `extract_receipt(images, categories=None, payment_methods=None, model=None, *, scope=None)` — meters when `scope` is given.
  - `transcribe_audio(data, filename, content_type, *, client=None, scope=None)` — one record per attempt.
  - `get_embedding(text, *, scope=None)` — meters when `scope` is given.

- [ ] **Step 1: Write the failing test**

Append to `src/backend/assistant/tests/test_metering.py`:

```python
async def test_a_receipt_photo_correlates_extraction_and_chat(
    async_client, logged_in, priced, receipt_image
):
    """DoD: a receipt-photo interaction produces correlated records."""
    from assistant.models import UsageInteraction, UsageKind, UsageRecord

    with extraction_override_stub(), agent_override_stub():
        resp = await async_client.post(
            "/assistant/chat/", data={"image": receipt_image}
        )
        [chunk async for chunk in resp.streaming_content]

    interaction = await UsageInteraction.objects.aget()
    kinds = [
        r.kind
        async for r in UsageRecord.objects.filter(interaction=interaction).order_by("created_at")
    ]
    assert UsageKind.EXTRACTION in kinds
    assert UsageKind.CHAT in kinds


async def test_the_vision_retry_produces_a_second_extraction_record(
    async_client, logged_in, priced, receipt_image
):
    """The expensive retry (views.py:438) is a separate billable call."""
    from assistant.models import UsageKind, UsageRecord

    with extraction_fails_then_succeeds_stub(), agent_override_stub():
        resp = await async_client.post("/assistant/chat/", data={"image": receipt_image})
        [chunk async for chunk in resp.streaming_content]

    count = await UsageRecord.objects.filter(kind=UsageKind.EXTRACTION).acount()
    assert count == 2


async def test_the_transcription_fallback_bills_twice(household, user, priced):
    """DoD: the fallback loop bills twice when the primary rejects the audio."""
    from assistant.agents.scope import AgentScope
    from assistant.models import UsageKind, UsageRecord
    from assistant.services.transcription import transcribe_audio

    scope = AgentScope(household=household, user=user)
    with fake_openai_first_model_fails() as client:
        await transcribe_audio(b"x", "a.webm", "audio/webm", client=client, scope=scope)

    recs = [r async for r in UsageRecord.objects.filter(kind=UsageKind.TRANSCRIPTION)]
    assert len(recs) == 2
    assert [r.ok for r in recs] == [False, True]


async def test_an_embedding_is_metered(household, user, priced):
    from assistant.models import UsageKind, UsageRecord
    from assistant.agents.scope import AgentScope
    from assistant.services.embedding import get_embedding

    with fake_openai_embeddings():
        await get_embedding("oi", scope=AgentScope(household=household, user=user))

    rec = await UsageRecord.objects.aget(kind=UsageKind.EMBEDDING)
    assert rec.model == "text-embedding-3-small"


def test_no_unmetered_provider_call_site_exists():
    """The ratchet. DoD: fails if a new unmetered call site is added.

    Every line that reaches a provider must sit in a module that imports
    `record_usage`. This is coarse on purpose — a precise AST check would be
    brittle, and coarse-but-loud beats precise-but-skipped. If you are adding a
    legitimate new call site, meter it; if you genuinely cannot, add it to
    EXEMPT with a comment saying why.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    CALL = re.compile(
        r"\.(run_stream|run)\(|"
        r"client\.audio\.transcriptions\.create\(|"
        r"\.embeddings\.create\("
    )
    EXEMPT = {
        # Test doubles and the eval harness make deliberate unmetered calls.
        "assistant/tests",
        "assistant/agents/analytics.py",  # no provider call; matches .run( by accident
    }

    offenders = []
    for path in root.rglob("*.py"):
        rel = str(path.relative_to(root))
        if any(rel.startswith(e) for e in EXEMPT) or "/migrations/" in rel:
            continue
        text = path.read_text(encoding="utf-8")
        if CALL.search(text) and "record_usage" not in text:
            offenders.append(rel)

    assert not offenders, (
        "Unmetered provider call sites (E07 S07-2):\n  " + "\n  ".join(offenders)
    )
```

> The stubs named above are placeholders. **Read the existing
> `test_receipt_flow.py`, `test_extraction.py` and `test_transcription.py`
> first** — they already contain working fakes for the extraction agent, the
> receipt upload and the OpenAI transcription client. Reuse those.

- [ ] **Step 2: Run test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_metering.py -v
```
Expected: FAIL — `test_no_unmetered_provider_call_site_exists` lists `assistant/agents/extraction.py`, `assistant/services/transcription.py`, `assistant/services/embedding.py`.

- [ ] **Step 3: Meter extraction**

In `src/backend/assistant/agents/extraction.py`, change the signature and the run:

```python
async def extract_receipt(
    images: list[tuple[bytes, str]],
    categories: list[str] | None = None,
    payment_methods: list[str] | None = None,
    model=None,
    *,
    scope=None,
) -> ReceiptExtraction:
    """Lê as fotos do recibo e devolve a extração estruturada.

    ``scope`` é o ``AgentScope`` da interação; quando dado, a chamada é
    contabilizada em ``UsageRecord`` (E07 S07-2). Opcional para que os testes
    de extração pura não precisem de um household.
    """
    ...
    resolved = model or settings.LLM_VISION_MODEL
    timer = Timer()
    try:
        with timer:
            result = await extraction_agent.run(prompt, model=model)
    except Exception:
        if scope is not None:
            await record_usage(
                interaction=getattr(scope, "interaction", None),
                household=scope.household,
                user=scope.user,
                kind=UsageKind.EXTRACTION,
                model=str(resolved),
                usage=None,
                latency_ms=timer.ms,
                ok=False,
            )
        raise
    if scope is not None:
        await record_usage(
            interaction=getattr(scope, "interaction", None),
            household=scope.household,
            user=scope.user,
            kind=UsageKind.EXTRACTION,
            model=str(resolved),
            usage=result.usage(),
            latency_ms=timer.ms,
            ok=True,
        )
    return result.output
```

Imports at the top: `from assistant.metering import Timer, record_usage` and `from assistant.models import UsageKind`.

> Watch for a circular import: `assistant.models` imports `accounts.models`, and `assistant.agents.extraction` is imported by `assistant.views`. If Django complains at startup, move the two imports inside the function body — that is the established pattern in this codebase (`views.py:198`, `:238`, `:348`, `:409`).

Then in `views.py`, pass `scope=scope` at both call sites (`:426` and `:438-441`).

- [ ] **Step 4: Meter transcription — every attempt in the loop**

In `src/backend/assistant/services/transcription.py`:

```python
async def transcribe_audio(
    data: bytes,
    filename: str,
    content_type: str,
    *,
    client: AsyncOpenAI | None = None,
    scope=None,
) -> str:
    ...
    last_exc: Exception | None = None
    for model in models:
        timer = Timer()
        try:
            with timer:
                result = await client.audio.transcriptions.create(
                    model=model,
                    file=(filename, data, content_type),
                    language="pt",
                )
            await _meter(scope, model, getattr(result, "usage", None), timer.ms, ok=True)
            return result.text.strip()
        except Exception as exc:
            last_exc = exc
            # Metered even though it failed: the provider charged for the
            # attempt. This loop is the reason E07's DoD has its own box for
            # "the transcription fallback bills twice".
            await _meter(scope, model, None, timer.ms, ok=False)
            logger.warning(
                "Transcrição falhou (modelo=%s, content_type=%s, %d bytes): %s",
                model,
                content_type,
                len(data),
                exc,
            )

    raise last_exc


async def _meter(scope, model, usage, latency_ms, *, ok):
    """Record one transcription attempt, if we know whose it was.

    Cost will be ``None``: providers price transcription per MINUTE of audio,
    and ``ModelPrice`` models token pricing only. That gap is deliberate and
    bounded — a transcription is roughly two orders of magnitude cheaper than a
    vision call (E01), so it does not move p50/p90/p99. Documented in the
    runbook; asserted by `test_pricing_gaps_are_declared`.
    """
    if scope is None:
        return
    from assistant.metering import record_usage
    from assistant.models import UsageKind

    await record_usage(
        interaction=getattr(scope, "interaction", None),
        household=scope.household,
        user=scope.user,
        kind=UsageKind.TRANSCRIPTION,
        model=model,
        usage=usage,
        latency_ms=latency_ms,
        ok=ok,
    )
```

Then in `views.py:307`, pass `scope=scope`.

- [ ] **Step 5: Meter embeddings**

In `src/backend/assistant/services/embedding.py`:

```python
async def get_embedding(text: str, *, scope=None) -> list[float] | None:
    """Get embedding vector for text using OpenAI API. Returns None on error.

    ``scope`` is the AgentScope of the interaction this embedding serves. It is
    optional because the semantic index can be rebuilt outside any request —
    ``UsageRecord.interaction`` is nullable for exactly that case (E07 S07-1).
    """
    from assistant.metering import Timer, record_usage
    from assistant.models import UsageKind

    timer = Timer()
    try:
        with timer:
            response = await async_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=text,
            )
    except Exception:
        if scope is not None:
            await record_usage(
                interaction=getattr(scope, "interaction", None),
                household=scope.household,
                user=scope.user,
                kind=UsageKind.EMBEDDING,
                model=EMBEDDING_MODEL,
                usage=None,
                latency_ms=timer.ms,
                ok=False,
            )
        return None
    if scope is not None:
        await record_usage(
            interaction=getattr(scope, "interaction", None),
            household=scope.household,
            user=scope.user,
            kind=UsageKind.EMBEDDING,
            model=EMBEDDING_MODEL,
            usage=response.usage,
            latency_ms=timer.ms,
            ok=True,
        )
    return response.data[0].embedding
```

And at `src/backend/assistant/agents/tools.py:1224`:

```python
    query_vector = await get_embedding(message, scope=scope)
```

> Confirm the local variable at that point is the `AgentScope` — read
> `check_memory` in `tools.py` first. If it is `ctx.deps`, pass `ctx.deps`.

- [ ] **Step 6: Run tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_metering.py -v
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
```
Expected: all pass, including the ratchet.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(assistant): meter extraction, transcription and embeddings

Every provider call now writes a UsageRecord, including the failures that still
cost money: the vision retry and each attempt of the transcription fallback
loop. A ratchet test fails if a new unmetered call site appears. Transcription
cost stays null — providers price it per minute, ModelPrice models tokens; the
gap is asserted and documented rather than papered over with a zero."
```

---

## Task 10: The operator report, the real credit grant, and the runbook

S07-5, plus spec D5 — the one number that could not be decided before real data.

**Files:**
- Create: `src/backend/assistant/management/commands/usage_report.py`
- Create: `src/backend/assistant/tests/test_usage_report.py`
- Modify: the beta `Plan` seed migration's `MONTHLY_CREDITS` (via a **new** migration; never edit an applied one)
- Modify: `docs/runbook.md`

**Interfaces:**
- Consumes: `UsageRecord`, `UsageInteraction`, `Plan`.
- Produces: `python manage.py usage_report [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--by-kind]`

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_usage_report.py`:

```python
"""The operator report — the numbers a price has to clear."""

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def _record(household, cost, kind="chat"):
    from assistant.models import UsageRecord

    return UsageRecord.objects.create(
        household=household, kind=kind, model="openai:test", cost_usd=Decimal(cost)
    )


def test_the_report_totals_cost_per_household(household):
    _record(household, "1.00")
    _record(household, "2.50")
    out = StringIO()
    call_command("usage_report", stdout=out)
    assert "3.50" in out.getvalue()


def test_the_report_shows_p50_p90_and_p99(household, other_household):
    """S07-5: the numbers a price must clear."""
    for _ in range(10):
        _record(household, "1.00")
    _record(other_household, "50.00")
    out = StringIO()
    call_command("usage_report", stdout=out)
    text = out.getvalue()
    assert "p50" in text and "p90" in text and "p99" in text


def test_the_report_breaks_cost_down_by_kind(household):
    """S07-5: what does receipt OCR cost relative to text chat?"""
    _record(household, "0.10", kind="chat")
    _record(household, "4.00", kind="extraction")
    out = StringIO()
    call_command("usage_report", "--by-kind", stdout=out)
    text = out.getvalue()
    assert "extraction" in text and "chat" in text


def test_the_report_counts_unpriced_records_instead_of_hiding_them(household):
    """A null cost is a KNOWN gap. Silently summing it as zero is a lie."""
    from assistant.models import UsageRecord

    UsageRecord.objects.create(
        household=household, kind="transcription", model="whisper-1", cost_usd=None
    )
    out = StringIO()
    call_command("usage_report", stdout=out)
    assert "sem preço" in out.getvalue()


def test_the_report_respects_the_date_window(household):
    _record(household, "9.99")
    out = StringIO()
    call_command("usage_report", "--since", "2099-01-01", stdout=out)
    assert "9.99" not in out.getvalue()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_usage_report.py -v
```
Expected: FAIL — `CommandError: Unknown command: 'usage_report'`

- [ ] **Step 3: Write the command**

Create `src/backend/assistant/management/commands/usage_report.py`:

```python
"""What each household costs, and the distribution a price has to clear.

E07 S07-5. Percentiles are computed in Python over per-household totals rather
than in SQL: the row count here is households, not records, so the simple thing
is correct and portable across the Supabase pooler.

Unpriced records are COUNTED and reported separately, never summed as zero. A
cost report that quietly treats "we don't know" as "free" is worse than no
report — it looks authoritative.
"""

from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Count, Sum

from assistant.models import UsageRecord


def percentile(values: list[Decimal], p: float) -> Decimal:
    """Nearest-rank percentile. Empty input -> 0."""
    if not values:
        return Decimal("0")
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round(p / 100 * len(ordered) + 0.5)) - 1))
    return ordered[idx]


class Command(BaseCommand):
    help = "Cost per household over a period, with p50/p90/p99 and a kind breakdown."

    def add_arguments(self, parser):
        parser.add_argument("--since", help="YYYY-MM-DD, inclusive")
        parser.add_argument("--until", help="YYYY-MM-DD, exclusive")
        parser.add_argument("--by-kind", action="store_true")

    def handle(self, *args, **opts):
        qs = UsageRecord.objects.all()
        if opts.get("since"):
            qs = qs.filter(created_at__gte=datetime.fromisoformat(opts["since"]))
        if opts.get("until"):
            qs = qs.filter(created_at__lt=datetime.fromisoformat(opts["until"]))

        rows = (
            qs.values("household__name")
            .annotate(total=Sum("cost_usd"), calls=Count("id"))
            .order_by("-total")
        )
        totals = [r["total"] or Decimal("0") for r in rows]

        self.stdout.write("Custo por casa (USD)")
        self.stdout.write("-" * 52)
        for r in rows:
            self.stdout.write(
                f"{(r['household__name'] or '—')[:30]:<32}"
                f"{r['total'] or Decimal('0'):>12}{r['calls']:>8}"
            )

        self.stdout.write("")
        self.stdout.write(f"casas ativas : {len(totals)}")
        self.stdout.write(f"p50          : {percentile(totals, 50)}")
        self.stdout.write(f"p90          : {percentile(totals, 90)}")
        self.stdout.write(f"p99          : {percentile(totals, 99)}")

        unpriced = qs.filter(cost_usd__isnull=True).count()
        if unpriced:
            self.stdout.write("")
            self.stdout.write(
                f"{unpriced} chamadas sem preço (não somadas). "
                f"Transcrição é cobrada por minuto e ModelPrice só modela tokens "
                f"— ver docs/runbook.md."
            )

        if opts.get("by_kind"):
            self.stdout.write("")
            self.stdout.write("Custo por tipo de chamada (USD)")
            self.stdout.write("-" * 52)
            for r in (
                qs.values("kind").annotate(total=Sum("cost_usd"), calls=Count("id")).order_by("-total")
            ):
                self.stdout.write(
                    f"{r['kind']:<32}{r['total'] or Decimal('0'):>12}{r['calls']:>8}"
                )
```

- [ ] **Step 4: Set the real credit grant (spec D5)**

Run against real data — locally against the friday dev copy, or production read-only:

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from django.db.models import Count
from django.db.models.functions import TruncDate
from assistant.models import ChatMessage, UsageInteraction
print('turns/day:')
for r in UsageInteraction.objects.annotate(d=TruncDate('created_at')).values('d','kind').annotate(n=Count('id')).order_by('-n')[:20]:
    print(' ', r)
print('chat messages/day:')
for r in ChatMessage.objects.annotate(d=TruncDate('created_at')).values('d').annotate(n=Count('id')).order_by('-n')[:20]:
    print(' ', r)
"
```

Take the observed daily p99 for text and image separately, convert to a monthly credit figure using the seeded `CreditPrice` grid, and set the grant **generously above** it — E01's precedent is "generous enough that real use never hits them". Then write a **new** migration (never edit an applied one):

```python
"""Replace the placeholder credit grant with a number from real data.

E07 spec D5. Observed on <DATE> over <N> days of real single-user usage:
  text  p99 = <X>/day  -> <X*30> turns/month at <c> credits = <...>
  image p99 = <Y>/day  -> <Y*30> turns/month at <c> credits = <...>
Grant set to <Z>, roughly <k>x the observed p99, per E01's precedent that a
beta ceiling real use never touches is the point.
"""

from django.db import migrations

NEW = 0  # <-- the number you computed
OLD = 5000


def up(apps, schema_editor):
    apps.get_model("accounts", "Plan").objects.filter(slug="beta").update(
        monthly_credits=NEW
    )


def down(apps, schema_editor):
    apps.get_model("accounts", "Plan").objects.filter(slug="beta").update(
        monthly_credits=OLD
    )


class Migration(migrations.Migration):
    dependencies = [("accounts", "00XX_seed_beta_plan")]
    operations = [migrations.RunPython(up, down)]
```

- [ ] **Step 5: Document in the runbook**

Append a section to `docs/runbook.md`, following the file's existing one-section-per-command style (full invocation with realistic values, what it prints, the common failure):

```markdown
## Usage, credits and cost (E07)

### Run the cost report

    POSTGRES_PORT=5433 uv run python src/backend/manage.py usage_report --by-kind --since 2026-08-01

Prints cost per household in USD sorted by spend, then p50/p90/p99 across
households, then a per-call-kind breakdown. **`sem preço` is not zero** — see
the known gap below.

Common failure: an empty report means `UsageRecord` has no rows in the window,
not that costs were zero. Widen `--since`.

### Change a model's price

Prices live in the database (`ModelPrice`), so this needs no deploy: Django
admin → Preços de modelo → add a row with a new `effective_from`. Never edit an
existing row — history is what makes an old `UsageRecord` explicable.

**Always re-check the provider's live pricing page first, and put its URL in
`source_url`.** Never write a price from memory: model catalogues churn faster
than anyone's recall, and a wrong number here becomes an authoritative-looking
figure in the report above. Same rule applies when choosing the ESSENTIAL
tier's free and cheapest-paid models at openrouter.ai/models.

### Change the credit grant or the credit prices

Admin → Planos → `monthly_credits` (grant per household per calendar month).
Admin → Preços em créditos → the (tier × kind) grid. Both take effect on the
next request; no deploy, no restart.

Credits are a **product currency, not tokens**. Real token counts are in
`UsageRecord`. Retuning either table never rewrites what a household has
already spent — `UsageInteraction.credits_charged` is frozen at write time.

### The three tiers

| Tier | pt-BR | Model setting | Credits |
|---|---|---|---|
| Advanced | Avançado | `LLM_TIER_ADVANCED` | most |
| Standard | Padrão | `LLM_TIER_STANDARD` | fewer |
| Essential | Essencial | `LLM_TIER_ESSENTIAL` (+ `_FALLBACK`) | zero |

A household picks its tier. When credits run out the chokepoint forces
Essential — it degrades, it does not refuse. The **abuse ceiling**
(`ASSISTANT_ABUSE_*`) is a different thing and *does* refuse, on every tier
including Essential; it is what keeps R0's "no unbounded LLM spend" guarantee
true.

### Known gap: transcription cost is null

Providers price transcription per minute of audio; `ModelPrice` models token
pricing only. Transcription records carry `ok`, `model` and latency but
`cost_usd = NULL`, and the report counts them under `sem preço`. Bounded on
purpose: a transcription is ~2 orders of magnitude cheaper than a vision call,
so it does not move p50/p90/p99. Revisit if audio volume grows.
```

- [ ] **Step 6: Run tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_usage_report.py -v
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(assistant): operator cost report, real credit grant, runbook

usage_report gives cost per household plus p50/p90/p99 and a per-kind
breakdown. Unpriced records are counted separately, never summed as zero. The
beta grant replaces its placeholder with a number derived from real usage."
```

---

## Task 11: Show the balance and let the user switch tier

S07-4's "visible to the user in the UI, not silently applied", and the DoD box for switching tier.

**Files:**
- Create: `src/backend/assistant/views.py::usage_view` and `tier_view`
- Modify: `src/backend/assistant/urls.py`
- Modify: `src/backend/frontend/src/cards/ChatWidget.tsx`
- Test: `src/backend/assistant/tests/test_views.py` (extend)

**Interfaces:**
- Consumes: `balance_for` (Task 6), `Tier` (Task 4).
- Produces:
  - `GET /assistant/usage/` → `{"granted": int, "remaining": int, "renews_on": "YYYY-MM-DD", "tier": "advanced", "tiers": [{"value","label"}]}`
  - `POST /assistant/tier/` with `{"tier": "standard"}` → `{"tier": "standard"}` or 400

- [ ] **Step 1: Write the failing test**

Append to `src/backend/assistant/tests/test_views.py`:

```python
async def test_usage_endpoint_reports_balance_and_tier(async_client, logged_in, household, plan):
    resp = await async_client.get("/assistant/usage/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["granted"] == plan.monthly_credits
    assert body["remaining"] == plan.monthly_credits
    assert body["tier"] == "advanced"
    assert {t["value"] for t in body["tiers"]} == {"advanced", "standard", "essential"}


async def test_usage_endpoint_requires_authentication(async_client):
    resp = await async_client.get("/assistant/usage/")
    assert resp.status_code == 403


async def test_a_user_can_switch_tier(async_client, logged_in, household):
    resp = await async_client.post(
        "/assistant/tier/", data={"tier": "standard"}, content_type="application/json"
    )
    assert resp.status_code == 200
    await household.arefresh_from_db()
    assert household.preferred_tier == "standard"


async def test_an_unknown_tier_is_rejected(async_client, logged_in, household):
    resp = await async_client.post(
        "/assistant/tier/", data={"tier": "godmode"}, content_type="application/json"
    )
    assert resp.status_code == 400
    await household.arefresh_from_db()
    assert household.preferred_tier == "advanced"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_views.py -v -k "usage_endpoint or switch_tier or unknown_tier"
```
Expected: FAIL — 404.

- [ ] **Step 3: Add the views**

Append to `src/backend/assistant/views.py`:

```python
@require_GET
async def usage_view(request):
    """The household's credit balance, renewal date and chosen tier.

    S07-4: the allowance is visible, not silently applied. A user who is being
    degraded has to be able to see why.
    """
    from django.contrib.auth import aget_user

    from assistant.quota import balance_for
    from core.tiers import Tier

    user = await aget_user(request)
    if not user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=403)

    household = getattr(request, "household", None)
    if household is None:
        return JsonResponse({"error": "Sem casa ativa."}, status=400)

    granted, remaining, renews_on = await balance_for(household)
    return JsonResponse(
        {
            "granted": granted,
            "remaining": remaining,
            "renews_on": renews_on.isoformat(),
            "tier": household.preferred_tier,
            "tiers": [{"value": t.value, "label": t.label} for t in Tier],
        }
    )


@require_http_methods(["POST"])
async def tier_view(request):
    """Let the household choose how fast it spends its credits (spec D2)."""
    from django.contrib.auth import aget_user

    from core.tiers import Tier

    user = await aget_user(request)
    if not user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=403)

    household = getattr(request, "household", None)
    if household is None:
        return JsonResponse({"error": "Sem casa ativa."}, status=400)

    try:
        tier = json.loads(request.body).get("tier")
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if tier not in Tier.values:
        return JsonResponse({"error": "Modo desconhecido."}, status=400)

    household.preferred_tier = tier
    await household.asave(update_fields=["preferred_tier"])
    return JsonResponse({"tier": tier})
```

And in `src/backend/assistant/urls.py`:

```python
from assistant.views import chat_view, history_view, tier_view, usage_view

urlpatterns = [
    path("chat/", chat_view, name="chat"),
    path("history/", history_view, name="history"),
    path("usage/", usage_view, name="usage"),
    path("tier/", tier_view, name="tier"),
]
```

- [ ] **Step 4: Surface it in the chat widget**

`ChatWidget.tsx` is 936 lines and already holds ~15 `useState` hooks. **Do not add four more inline.** Extract a small hook and a presentational component:

- Create `src/backend/frontend/src/cards/useCredits.ts` — fetches `usage/` on mount and after each completed turn, exposes `{granted, remaining, renewsOn, tier, tiers, setTier}`.
- Create `src/backend/frontend/src/cards/CreditBadge.tsx` — renders the balance, the renewal date, and a tier selector; posts to `tier/` with the same `X-CSRFToken` header pattern `ChatWidget.tsx` already uses for `chat/` (read the `fetch` at `:372` and copy its credential and header handling exactly — the TWA/CSRF behaviour there is hard-won).
- In `ChatWidget.tsx`: render `<CreditBadge/>` in the panel header, and handle the new `{"type":"notice"}` SSE event by rendering it as a system line above the assistant's reply.

**This is daisyUI work, so it goes through the Blueprint MCP chain** (`daisyui_setup_expert` → `daisyui_rules_enforcer` → `daisyui_component_syntax_expert` → write → `daisyui_quality_inspector` with `auditIntent: "fix_changes"`). Skip `daisyui_creative_director` and `daisyui_page_architect`: this project has a settled design direction, and the badge must match the existing widget rather than introduce an aesthetic.

- [ ] **Step 5: Rebuild the frontend bundle**

`mount.js` and `tailwind.css` are git-tracked build artifacts. New Tailwind classes will not appear without a forced rebuild:

```bash
cd src/backend/frontend && npm run build -- --force
```

Then confirm the new classes actually landed in the committed CSS before moving on.

- [ ] **Step 6: Run tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(assistant): show the credit balance and let the user switch tier

S07-4: the allowance is visible, not silently applied. A degrade arrives as an
SSE notice above the reply, so a user who lands on Essencial can see why and
when their credits renew."
```

---

## Task 12: Close E06's two dashboard tiles

Inherited debt, named explicitly in E06's closing note and in this epic's Out of scope. The golden-signals dashboard shipped with four tiles because assistant turns and LLM spend lived only in Postgres, which Cloud Monitoring cannot read. The tables from Tasks 1–9 make them possible.

**Files:**
- Create: `src/backend/core/management/commands/emit_usage_metrics.py`
- Modify: `docs/runbook.md`
- Modify: `docs/backlog/E06-observability-and-agent-tracing.md` (tick the dashboard box)
- Test: `src/backend/core/tests/test_usage_metrics.py`

**Interfaces:**
- Consumes: `UsageRecord`, `UsageInteraction`.
- Produces: `python manage.py emit_usage_metrics` — writes one structured log line per day's aggregate, which Cloud Logging parses into `jsonPayload` fields a log-based metric can count.

**Why a log line rather than the Monitoring API:** E06 established that structured JSON on stdout is how this service talks to Cloud Logging (`core/log_formatting.py`), and a log-based metric needs no new IAM role, no new client library, and no new failure mode in the request path. The uptime check already proves the service is alive; this only needs a daily heartbeat.

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_usage_metrics.py`:

```python
"""The daily aggregate line Cloud Logging turns into dashboard tiles."""

import json
from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def test_it_emits_one_parseable_json_line(household, caplog):
    from assistant.models import InteractionKind, UsageInteraction, UsageRecord

    UsageInteraction.objects.create(
        household=household, user=None, kind=InteractionKind.TEXT
    )
    UsageRecord.objects.create(
        household=household, kind="chat", model="openai:test", cost_usd=Decimal("1.50")
    )
    out = StringIO()
    call_command("emit_usage_metrics", stdout=out)
    payload = json.loads(out.getvalue().strip().splitlines()[-1])
    assert payload["metric"] == "assistant_usage_daily"
    assert payload["turns"] == 1
    assert payload["cost_usd"] == "1.50"


def test_a_quiet_day_still_emits_zeroes(caplog):
    """A missing line is indistinguishable from a broken job. Emit zeroes."""
    out = StringIO()
    call_command("emit_usage_metrics", stdout=out)
    payload = json.loads(out.getvalue().strip().splitlines()[-1])
    assert payload["turns"] == 0
    assert payload["cost_usd"] == "0"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_usage_metrics.py -v
```
Expected: FAIL — `CommandError: Unknown command`.

- [ ] **Step 3: Write the command**

```python
"""Emit yesterday's assistant usage as one structured log line.

E06 shipped a four-tile golden-signals dashboard because two of its five
signals — assistant turns/day and LLM spend/day — could not be built: a
successful request emits no application log line, and turn counts lived only in
Postgres, which Cloud Monitoring cannot read. E07 created the tables; this
command bridges them to Cloud Logging, where a log-based metric can count them.

A quiet day emits zeroes rather than nothing: a missing line is
indistinguishable from a broken job, and a dashboard that silently flatlines is
worse than one that reads zero.
"""

import json
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from assistant.models import UsageInteraction, UsageRecord


class Command(BaseCommand):
    help = "Emit yesterday's assistant turns and LLM spend as a structured log line."

    def add_arguments(self, parser):
        parser.add_argument("--day", help="YYYY-MM-DD (default: yesterday)")

    def handle(self, *args, **opts):
        if opts.get("day"):
            from datetime import date

            day = date.fromisoformat(opts["day"])
        else:
            day = (timezone.localtime() - timedelta(days=1)).date()

        start = timezone.make_aware(
            timezone.datetime.combine(day, timezone.datetime.min.time())
        )
        end = start + timedelta(days=1)

        turns = UsageInteraction.objects.filter(
            created_at__gte=start, created_at__lt=end
        ).count()
        cost = UsageRecord.objects.filter(
            created_at__gte=start, created_at__lt=end
        ).aggregate(t=Sum("cost_usd"))["t"] or Decimal("0")

        self.stdout.write(
            json.dumps(
                {
                    "metric": "assistant_usage_daily",
                    "day": day.isoformat(),
                    "turns": turns,
                    "cost_usd": str(cost),
                }
            )
        )
```

- [ ] **Step 4: Provision the metrics and tiles**

```bash
# Log-based metrics over the line the command emits
gcloud logging metrics create assistant_turns_daily \
  --description="Assistant turns per day (E07)" \
  --log-filter='jsonPayload.metric="assistant_usage_daily"' \
  --value-extractor='EXTRACT(jsonPayload.turns)'

gcloud logging metrics create assistant_cost_daily \
  --description="LLM spend USD per day (E07)" \
  --log-filter='jsonPayload.metric="assistant_usage_daily"' \
  --value-extractor='EXTRACT(jsonPayload.cost_usd)'
```

Then add two tiles to dashboard `450cfbfa-635f-487b-9893-83947ab91b9b` (`expense-tracker — golden signals`) and **remove the note on its face saying the two tiles are impossible** — that note was accurate for E06 and is now stale.

Schedule the daily run with Cloud Scheduler hitting a Cloud Run job, or — cheaper and consistent with how this project already avoids paid infrastructure — as a step in the existing deploy/cron path. Record whichever you choose in the runbook.

- [ ] **Step 5: Update the runbook and tick E06's box**

Add an `### Emit the daily usage metric` subsection to the E07 runbook section from Task 10, with the full invocation and what a missing line means. Then in `docs/backlog/E06-observability-and-agent-tracing.md`, change the dashboard assertion from `- [ ]` to `- [x]` and replace its "four of five, and the gap is structural" text with what actually shipped.

- [ ] **Step 6: Run tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/ -q
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(core): daily usage metric closes E06's two dashboard tiles

E06's golden-signals dashboard shipped with four of five signals because turn
counts and LLM spend lived only in Postgres. E07's tables plus one structured
log line per day give Cloud Logging something to build a log-based metric on."
```

---

## Final verification

Run the epic's Definition of Done in full and paste the output as evidence (`superpowers:verification-before-completion`).

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
uv run python src/backend/manage.py makemigrations --check --dry-run
uv run python src/backend/manage.py check
DEBUG=False SECRET_KEY=<50+ chars> ALLOWED_HOSTS=example.com \
  uv run python src/backend/manage.py check --deploy
```

Then walk the epic's observable assertions one by one. Three need evidence beyond a green suite:

- **Row count preserved across the rename.** Capture `SELECT count(*)` before and after `migrate` on a copy of the production database, not on a fresh test DB.
- **The operator report against real beta data.** Paste actual `usage_report --by-kind` output. Placeholder numbers do not close this box.
- **`grep` proves one enforcement path.** `test_there_is_exactly_one_enforcement_path` covers it, but run the grep by hand once and paste it.

Then: `/security-review` (the epic's pipeline inserts it before verification — quota bypass is the abuse vector; verify no path reaches a model without passing `decide()`), `superpowers:requesting-code-review`, and `superpowers:finishing-a-development-branch`.

---

## Self-review notes

Checked against the spec after writing:

- **S07-1** → Tasks 1, 3, 5. Every field the story lists is present. "Never fails the user's request" is Task 3 Step 1's `test_a_metering_failure_never_reaches_the_caller`. "Price table is configuration, not hardcoded" → Task 2, database-backed per spec D4.
- **S07-2** → Tasks 8, 9. All five call sites, the vision retry, the transcription fallback, and the ratchet test the DoD demands.
- **S07-3** → Tasks 6, 7. One function; `throttling.py` deleted and kept deleted by a test.
- **S07-4** → Tasks 5, 10, 11. Grant, credit grid, visible balance, tier switch, configurable without a deploy.
- **S07-5** → Task 10. p50/p90/p99, per-kind breakdown, runbook.
- **D1–D5** → Tasks 1, 4, 5, 6, 10 respectively. D5 is the only one that stays open into execution, and it is flagged as a placeholder in the migration docstring, in the test, and here.
- **E06 inherited debt** → Task 12.

Two known soft spots, called out rather than hidden:

1. **The test stubs in Tasks 7, 8 and 9** name helpers (`agent_override_stub`, `extraction_override_stub`, `fake_openai_first_model_fails`) that do not exist yet. The suite already contains working equivalents in `test_views.py`, `test_receipt_flow.py`, `test_extraction.py` and `test_transcription.py`. Each step says to read those first and reuse. This is the one place the plan asks the implementer to look something up rather than handing it over.
2. **Task 12's dashboard work is console/gcloud**, not code, so it cannot be proven by the test suite. Its test covers the log line; the tiles need a screenshot or a `gcloud monitoring dashboards describe` as evidence.
