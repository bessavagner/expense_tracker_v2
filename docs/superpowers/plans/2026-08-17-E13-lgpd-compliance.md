# E13 · LGPD compliance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make it lawful to hold a Brazilian household's complete financial history — the user can see everything the product knows about them, correct it, export it and delete it; nothing is kept forever by accident; and the privacy notice describes the code that actually runs.

**Architecture:** One registry — `core/privacy/inventory.py` — names every model in the project, what it is processed for, its lawful basis, what happens to it when a member leaves, and how long it is kept. Four things read that single list: the deletion service, the retention purge job, the privacy notice's retention table, and a test that fails when a model is added without a privacy decision. Nothing else in this epic maintains a parallel list of models, because a second list is how the notice and the code start disagreeing. The user-facing surface is one new **Privacidade** tab on the Conta page E18 shipped, plus two public pages for the notice and the terms.

**Tech Stack:** Django 6, django-allauth 65.19.1, django-htmx, HTMX 2.0.4, Alpine 3.14.8, daisyUI 5 / Tailwind, pytest + model-bakery + time-machine, Cloud Scheduler + Cloud Run Jobs.

**Spec:** [`docs/backlog/E13-lgpd-compliance.md`](../../backlog/E13-lgpd-compliance.md) — this epic is self-contained by design (`INDEX.md` preamble) and is the spec this plan argues from. The four policy questions it left open were decided before this plan was written; they are D1–D4 below.

**Epic:** E13 · LGPD compliance — R3, and the **last** of R3's four gate conditions (`INDEX.md` §3). Both dependencies are closed: E12 (2026-08-16, revision `expense-tracker-00048-lgf`) and E18 (2026-08-16, commit `65a1c7d`).

**Baseline commit:** `65a1c7d`. Every file:line reference below was read at that commit.

> **This is engineering, not legal advice.** The DoD's last assertion — *a Brazilian lawyer has reviewed the notice and terms* — cannot be satisfied by any task in this plan. Task 14 is where it is recorded as outstanding.

---

## Global Constraints

Copied verbatim from `docs/backlog/INDEX.md` §7. Every task's requirements implicitly include this section; violating any of these fails review regardless of whether the DoD passes.

1. **TDD.** Test first, always. Project convention, not a preference.
2. **Worktrees.** Feature work happens in an isolated worktree.
3. **The money boundary holds.** The LLM proposes structured intent; **Python computes every number**. No epic may move arithmetic into a prompt. *(No LLM call is added by this epic. One is **gated** — Task 4.)*
4. **Tenant scoping is centralized.** After E04, no epic may write `filter(user=...)` on a domain model. Use the household-scoped manager (`.for_household(...)` / `.for_request(...)`). **This epic has one narrow, explicit exception, and it is Task 6:** deleting a person's own rows *is* a per-user query by definition, and it runs inside `core/privacy/deletion.py` and nowhere else. Every read path in this epic still goes through the scoped manager.
5. **Coverage gate.** `coverage report --fail-under=80` must keep passing.
6. **Lint gate.** `ruff check` and `ruff format --check` clean. Line length 100, target py312.
7. **No new secret in git.** Env var + Secret Manager, and `.env.example` updated. *(This epic adds four non-secret env vars for the controller's identity — Task 11. A CNPJ is public record, not a secret, but it still goes through the same mechanism because settings that differ per environment belong there.)*
8. **pt-BR in the product UI, English in code, comments, and docs.** Existing convention. **The privacy notice and terms are product UI and are written in pt-BR** — S13-4 requires it explicitly.
9. **Migrations are reversible** or the epic states explicitly why not. This epic ships **two** migrations (Tasks 2 and 5); both are reversible.
10. **No time-bomb tests.** Any date-sensitive test freezes the clock. See `docs/testing-conventions.md`. **Half the tests in this epic are date-sensitive** — retention is arithmetic on `created_at`. Freeze at midday UTC, per that document.

### Additional constraint — the daisyUI Blueprint chain is mandatory for every UI task

`daisyui` is in the Tailwind entry CSS, so the licensed Blueprint MCP server governs all markup here. Tasks 3, 7, 8 and 11 each write UI. **Each of those tasks, run by whichever agent picks it up, must:**

1. `daisyui_setup_expert` — its **own** lowercase `workflowId` (suggested: `e13-signup`, `e13-privacidade`, `e13-exclusao`, `e13-legal`), absolute `projectRoot` = `/home/bessa/Documents/projetos/expense_tracker_v2`, `install: false`.
2. `daisyui_rules_enforcer` — same `workflowId`.
3. **Skip `daisyui_creative_director` and `daisyui_page_architect`.** This repo has a settled design direction; generating a competing aesthetic is actively harmful here.
4. `daisyui_component_syntax_expert` — **before writing markup**. Submit every component ID the task needs. Repeat with the same `workflowId` until the final batch advances the workflow.
5. Write the markup.
6. `daisyui_quality_inspector`, `auditIntent: "fix_changes"`, paths **relative to projectRoot**, line ranges from `git diff --unified=0`. Fix and rerun until it finalizes.

Three recorded, intentional deviations the Inspector will flag — **do not "fix" any of them**:

- `btn-accent` is this repo's established action colour (`templates/account/password_reset.html:26`, `templates/accounts/_members.html`).
- daisyUI 5 dropped `form-control` and `label-text`. Use `fieldset` / `label`, as the existing templates already do.
- The legal pages use `prose`-style authored spacing on a long document. That is structure, not decoration, and the Inspector's "static utilities in markup" rule targets decorative effects.

---

## Decisions taken before this plan

D1–D4 answer the epic's four open questions and are **settled**. D5–D12 are decisions this plan makes, each verified against the repo at `65a1c7d` rather than assumed.

| # | Decision | Why |
|---|---|---|
| **D1** | **A member leaving does not destroy the household.** Their `Membership` goes, their own authored chat, memory rules and receipt drafts go, every other `created_by` is already `SET_NULL` so the ledger survives for whoever remains. If they were the **last owner** and members remain, the **longest-standing remaining member is promoted to owner**. If they were the **last member**, the household is deleted and cascades everything. | Epic open question 4. The household's shared financial history belongs to the people still using it; the leaver's own words do not. `accounts/models.py:109` already says this is what E13 would do: *"E13 promotes the longest-standing member when the last owner deletes their account."* |
| **D2** | **Retention periods**, all carried in the inventory rather than in scattered settings: chat **90 days**; receipt drafts **90 days**; abandoned import jobs **180 days**; export job rows **180 days**; invitations **180 days**; usage records and interactions **730 days**; product events **730 days**; feedback **730 days**; admin access log **730 days**; task runs **90 days**; login attempts **30 days**; expired sessions **immediately**. Memory rules, and the ledger itself, are kept for the life of the account. | Epic open question 3. The assistant reads only the last `ASSISTANT_MAX_HISTORY` (=20, `settings.py:360`) messages, so 90 days costs the product nothing and is a number that reads honestly in a notice. 730 days on metering is the billing and abuse-evidence window E15 will need. |
| **D2a** | **Correction to the brainstorm:** the brainstorm said *import files: 180 days*. The repo already deletes the uploaded blobs at **7 days** via a GCS lifecycle rule (`settings.py:555`, E12 decision 2), which is stronger and is enforced by infrastructure rather than by our cron. **That stays at 7.** The 180 days applies to abandoned `ImportJob` **rows**, which are metadata, not files. | The notice must state what the code does. Weakening a live 7-day deletion to match a plan written in the abstract would be the exact failure mode S13-4 warns about. |
| **D3** | **Lawful basis per purpose.** Bookkeeping, authentication and backups: **execução de contrato**, LGPD art. 7º, V. The AI assistant — chat, memory rules, embeddings, receipt OCR, transcription: **consentimento**, art. 7º, I, revocable, with the rest of the product working without it. Abuse limits, security logs and metering: **legítimo interesse**, art. 7º, IX. | Epic open question 1. Contract is the stronger footing for the core product than legitimate interest, because the user signed up for exactly this. Consent for the LLM leg is what makes "we send your words to OpenAI" a choice rather than a disclosure. |
| **D3a** | **Consent must therefore be revocable, so Task 4 builds the revocation.** A notice that claims consent while the product cannot be used without it is a false notice. The assistant refuses with a 403 and a pt-BR explanation when consent is absent. | The epic's own warning: *"If the policy and the code disagree, the code is the violation."* |
| **D3b** | **Consent is asked in context, at first use — not as a checkbox on the signup form.** Signup carries one mandatory checkbox for the terms and the notice. The AI ask happens the first time the user opens the assistant. | Consent must be specific and informed; a checkbox bundled with three others is neither. It also protects E11's activation metric, which runs through the assistant. |
| **D4** | **The controller is a CNPJ the operator already holds.** Its razão social, CNPJ, address and privacy contact are four environment variables read into `settings.PRIVACY_CONTROLLER`, rendered by the notice, and asserted non-empty by a deploy check. | Epic's DoD needs a named controller. Putting it in settings means the notice cannot be deployed half-filled without the check failing. |
| **D5** | **One registry, `core/privacy/inventory.py`, is the epic's spine.** Deletion, retention, the notice's retention table and the completeness test all read it. No second list of models exists anywhere in this epic. | Every LGPD failure in a young product is a list that drifted. `core/tests/test_metrics_doc.py` is the precedent this copies: a document is only a contract if a test enforces it. |
| **D6** | **No new Django app.** Models go in `core/models.py` (they hang off `CustomUser`, which lives there); the services go in a `core/privacy/` package, following `core/tasks/`'s precedent; the tab goes in `accounts/views_account.py`, the home E18 declared for it (`views_account.py:4`). | Five apps is the shape of this repo. A sixth for four models and three services is ceremony. |
| **D7** | **The purge is a management command that enqueues a task**, run by a **Cloud Run Job** on a Cloud Scheduler trigger — not a new HTTP endpoint. | The service is deployed `--allow-unauthenticated`, so every new public path is a new thing to defend (`core/tasks/auth.py` exists precisely because of that). A Cloud Run Job runs the command with the service's own identity and no public surface. Enqueuing through `core.tasks.enqueue` means the run is **observable for free**: a `TaskRun` row with a status, an attempt count and a `last_error`, already in the admin (`core/admin.py:30`) and already in the runbook's dead-letter procedure. |
| **D8** | **The purge task's payload carries the date**, so `enqueue`'s content-hash idempotency (`core/tasks/enqueue.py:30-40`) makes it *exactly once per day* with no extra machinery. | A second Scheduler firing on the same day is a no-op rather than a double sweep. |
| **D9** | The new command is named **`purge_expired_data`**, not `retention_*`. | `core/management/commands/retention_report.py` already exists and is about **cohort** retention (E14). Two meanings of "retention" one tab-completion apart is a foot-gun. |
| **D10** | **`assistant.UsageInteraction.user` changes from `CASCADE` to `SET_NULL`** (Task 5). | Found while planning, and it is a real inconsistency: every other authored model is `SET_NULL` so *"deleting a person must never delete the family's financial history"* (`accounts/models.py:157-167`, asserted at `test_tenancy_bases.py:66`). `UsageInteraction` alone cascades, so today one member deleting their account silently erases the household's credit-charge history — and, through it, part of what E15 will bill from. |
| **D11** | **The export gains four sections rather than a second export path**: `conta`, `eventos`, `feedbacks`, `uso`. | E12 S12-4 already ships portability, already includes chat and memory rules (`export_builder.py:331-350`), and E13's scope says it *consumes* that machinery. But `core.ProductEvent`'s own docstring says it is *"exported by E13"* (`core/models.py:155`) and `core.Feedback`'s says it has *"its own entry on E13's processing inventory"* — those two promises are unkept until this task lands. |
| **D12** | **The chat purge deletes receipt drafts as a side effect, and that is intended.** `ReceiptDraft.chat_message` is `CASCADE`. | Both are 90 days, so the cascade only ever deletes something already due. The test asserts it, so nobody later "fixes" the cascade and quietly extends draft retention. |
| **D13** | **E13 builds the project's first scheduled job**, and must answer E12's recorded objection to crons head-on. | `settings.py:553-555` says, in as many words: *"Enforced by a GCS lifecycle rule, not by application code — **a deletion that depends on our cron running is a deletion that does not happen**."* That is a real decision and E13 cannot ignore it. **The answer is that E13's targets are database rows, for which no lifecycle rule exists** — the choice is a cron or nothing, not a cron or something better. So the objection is met by making the cron's *absence detectable* rather than by pretending it cannot fail: every run writes a `TaskRun` row, the runbook carries a one-command "did last night's run happen?" query, and Task 9 provisions a Monitoring alert that fires when a day passes with no successful run. A silent stop is the failure mode E12 named; this is what makes it non-silent. |
| **D14** | **`MemberRemoveView`'s 400 on removing the last owner stays.** | Found while planning. `accounts/views.py:127-139` refuses with *"A casa precisa de pelo menos um dono. Promova outra pessoa antes."* and comments that E13 owns the real semantics. It does — but for a *different* operation. An owner **removing somebody else** and an owner **deleting their own account** are not the same act, and only the second one implies consent to hand the house over. The 400 is correct and untouched; the promotion in Task 6 applies only to self-deletion. |

### The epic's evidence table has one stale row — do not repeat it

`docs/backlog/E13-lgpd-compliance.md:45` says: *"Deleting a user cascades the entire ledger with no export gate — `finances/models/entry.py:17` — `on_delete=CASCADE`"*. That was written 2026-08-07, before E04 phase 4. At `65a1c7d` it is **false in the way that matters**:

- `entry.py:26-31` — the `CASCADE` at that location is on **`household`**, not on the user.
- `accounts/models.py:169-175` — `created_by` is already `SET_NULL, null=True`.
- `accounts/tests/test_tenancy_bases.py:66-72` already asserts it.

So the ledger already survives a person's deletion. What does **not** exist is any of: an entry point to delete an account, an export-first gate, membership handover, session and login-attempt cleanup, and the one FK (D10) that still cascades. That is the actual gap, and it is what Tasks 5, 6 and 8 close.

---

## Reference facts verified at `65a1c7d` — trust these instead of re-deriving them

| Fact | Where |
|---|---|
| Every model in the project — **37** of them | enumerated in Task 1's registry; produced by `apps.get_models()` |
| Every FK to the user model and its `on_delete` | Task 1's table; only `account.EmailAddress`, `accounts.Membership`, `admin.LogEntry`, `mfa.Authenticator` and (until Task 5) `assistant.UsageInteraction` are `CASCADE` |
| `AuthoredHouseholdModel.created_by` is `SET_NULL` | `src/backend/accounts/models.py:157-175` |
| `HouseholdOwnedModel.household` is `CASCADE, null=False` | `src/backend/accounts/models.py:131-151` |
| `household_owned_models()` — discovery, not a hand-list | `src/backend/accounts/models.py:181-194` |
| The doc-is-a-contract test idiom to copy | `src/backend/core/tests/test_metrics_doc.py` |
| The model-enumeration test idiom to copy | `src/backend/accounts/tests/test_tenancy_bases.py:75-123` |
| `_TabView` — fragment for HTMX, whole page otherwise | `src/backend/accounts/views_account.py:31-52` |
| The tab-button markup to copy verbatim | `src/backend/templates/accounts/account_page.html:42-46` |
| The generic standalone wrapper, already renders `messages` | `src/backend/templates/accounts/tab_page.html` |
| `enqueue(name, payload, *, idempotency_key=None) -> TaskRun`, content-hash idempotent | `src/backend/core/tasks/enqueue.py:43` |
| `@task_handler(name, *, max_attempts=5)`, returns the function unchanged | `src/backend/core/tasks/registry.py:41` |
| Handlers are discovered from each app's `tasks` module — the filename is the contract | `src/backend/core/tasks/registry.py:72-78` |
| A handler that raises earns a retry; that is the documented signal | `src/backend/assistant/tasks.py:38-42` |
| `CLOUD_TASKS_ENABLED=0` runs handlers in-process at enqueue time | `src/backend/core/tasks/backends.py:21-39` |
| The export archive: 7 CSVs + `ledger.json` + `LEIA-ME.txt`; chat and memory rules are already in `ledger.json` | `src/backend/finances/services/export_builder.py:24-34, 331-350` |
| Export URL names: `finances:export_page`, `finances:export_request`, `finances:export_download` | `src/backend/finances/urls.py:237-239` |
| `ExportJob` statuses `pending/running/done/failed`; the row outlives the file | `src/backend/finances/models/export_job.py:8-27` |
| The chat chokepoint, before any model call | `src/backend/assistant/views.py:292-298` |
| Receipt images and audio are read into memory and never written anywhere — the notice's most important factual claim | `src/backend/assistant/views.py:505` and `:388-390`; neither path touches `core.storage`. **The epic cites `:288` for this; that line has moved** |
| The chat widget renders `{"error": "..."}` from any non-OK response as the assistant's reply — **so a 403 needs no front-end change** | `src/backend/frontend/src/cards/ChatWidget.tsx:53-58, 471-474` |
| `ACCOUNT_ADAPTER` is explicitly the allauth default, so a form hook is a one-line settings change | `src/backend/config/settings.py:298` |
| `ACCOUNT_SIGNUP_FORM_CLASS` is the supported extension point in 65.19.1; the class must define `signup(self, request, user)` | `.venv/.../allauth/account/internal/flows/signup.py:20-25, 28-41` |
| `custom_signup(request, user)` runs **after** `save_user`, so the user has a pk | `.venv/.../allauth/account/forms.py:417-427` |
| Sentry: `send_default_pii=False`, `before_send=scrub_event`; the scrubber drops request `data/cookies/headers/env`, frame `vars`, `extra`, breadcrumb `data` | `src/backend/core/observability.py:19-124` |
| Email goes through Resend over SMTP | `src/backend/config/settings.py:324-336` |
| `_ONBOARDING_EXEMPT_PREFIXES` — a public page not listed here 302s a signed-in, unonboarded user to the setup flow | `src/backend/accounts/middleware.py:91-102` |
| `base_public.html` centres its child in a flex `main`; a tall document needs `self-start` on the wrapper or its top is clipped | `src/backend/templates/base_public.html:35-45` |
| **There is no scheduled job of any kind in this project.** `expense-tracker-keepalive` was **deleted 2026-08-14** (E06 plan step 6) and replaced by a Monitoring uptime check; `gcloud scheduler jobs list` returns nothing. The `gcloud scheduler jobs create` block at `docs/runbook.md:716` is inside a "**the rest of this section is history, kept for the recreate command**" note — it is not current state | `docs/runbook.md:669-690` and `:760-775` |
| Two commands document a schedule they have never had: `sweep_stuck_import_jobs` ("Schedule it next to the keepalive ping") and `emit_usage_metrics` ("record whichever you pick here" — never picked) | `docs/runbook.md:1677`, `:1811-1813` |
| `model_bakery` cannot invent a pgvector `VectorField` — `assistant.MemoryEmbedding` needs `{"embedding": [0.1] * 1536}` passed explicitly | `src/backend/accounts/tests/test_cross_household_isolation.py:42-50` (`_extras`) |
| `MemberRemoveView` refuses to remove the last owner with a 400, and its comment says E13 owns the real semantics | `src/backend/accounts/views.py:127-139` |
| Committed frontend artifacts: rebuild Tailwind with `--force` or new classes silently do not exist | `docs/runbook.md:818-845` |

---

## File Structure

**Create**

| File | Responsibility |
|---|---|
| `src/backend/core/privacy/__init__.py` | The package's public surface: `INVENTORY`, `delete_account`, `purge_expired`. Nothing else is imported from one layer down — same discipline as `core/tasks/__init__.py` |
| `src/backend/core/privacy/inventory.py` | The registry. One `Record` per model in the project: purpose, lawful basis, disposal on a member leaving, retention. The single source every other file here reads |
| `src/backend/core/privacy/deletion.py` | `delete_account(user)` — the whole of D1, in one transaction |
| `src/backend/core/privacy/retention.py` | `purge_expired(as_of)` — walks the registry, deletes what is due, returns counts |
| `src/backend/core/privacy/consent.py` | `has_ai_consent(user)`, `set_ai_consent(user, granted)`, and the sync/async pair the chat view needs |
| `src/backend/core/tasks_privacy.py` | *(no — see `core/tasks.py` below)* |
| `src/backend/core/tasks.py` | The app-level `tasks` module the registry autodiscovers. `core` has none today; the purge handler is its first entry |
| `src/backend/core/management/commands/purge_expired_data.py` | The Cloud Run Job entry point. Enqueues, prints, exits |
| `src/backend/core/views_legal.py` | The two public documents, and the `robots`-safe `TemplateView`s that serve them |
| `src/backend/accounts/forms_signup.py` | `LedgerSignupForm` — the terms checkbox, and the `PolicyAcceptance` rows it writes |
| `src/backend/templates/accounts/_privacy_tab.html` | The Privacidade fragment |
| `src/backend/templates/accounts/_privacy_delete.html` | The deletion confirmation fragment, swapped into the tab |
| `src/backend/templates/accounts/account_deleted.html` | The one page a deleted user sees, rendered logged-out |
| `src/backend/templates/legal/base_legal.html` | Wide-prose wrapper over `base_public.html` |
| `src/backend/templates/legal/privacidade.html` | The privacy notice, pt-BR |
| `src/backend/templates/legal/termos.html` | The terms of service, pt-BR |
| `docs/architecture/data-inventory.md` | The sub-processor and data-flow inventory (S13-6), kept next to the notice |
| `src/backend/core/tests/test_privacy_inventory.py` | Every model is classified; every sub-processor is documented |
| `src/backend/core/tests/test_privacy_deletion.py` | The parameterized "nothing personal survives" suite, plus every household edge case |
| `src/backend/core/tests/test_privacy_retention.py` | The purge, frozen-clock, per model |
| `src/backend/core/tests/test_privacy_consent.py` | The assistant refuses without consent; the toggle grants and revokes |
| `src/backend/core/tests/test_legal_pages.py` | The documents are public, reachable, versioned, and say what the code does |
| `src/backend/core/tests/test_sentry_scrubbing.py` | The scrubber is verified against the inventory, not assumed |
| `src/backend/accounts/tests/test_privacy_tab.py` | The tab: what it shows, what it refuses to show a neighbour |
| `src/backend/accounts/tests/test_account_deletion_flow.py` | The UI path end to end |
| `src/backend/accounts/tests/test_signup_records_acceptance.py` | Signup writes the acceptance rows, at the current versions |

**Modify**

| File | Change |
|---|---|
| `src/backend/core/models.py` | Add `PolicyDocument`, `PolicyAcceptance`, `ConsentPurpose`, `Consent` |
| `src/backend/assistant/models.py` | `UsageInteraction.user` → `SET_NULL, null=True` (D10) |
| `src/backend/config/settings.py` | `ACCOUNT_SIGNUP_FORM_CLASS`, `PRIVACY_CONTROLLER`, `PRIVACY_POLICY_VERSION`, `TERMS_VERSION` |
| `src/backend/config/urls.py` | `/privacidade/`, `/termos/` |
| `src/backend/accounts/urls.py` | Four new routes under `conta/privacidade/` |
| `src/backend/accounts/views_account.py` | `PrivacyTabView`, `MemoryRuleDeleteView`, `AIConsentView`, `AccountDeleteView` |
| `src/backend/accounts/middleware.py` | `_ONBOARDING_EXEMPT_PREFIXES` gains `/privacidade/` and `/termos/` |
| `src/backend/templates/accounts/account_page.html` | A fourth `<button role="tab">` |
| `src/backend/templates/account/signup.html` | The acceptance checkbox |
| `src/backend/templates/base_public.html` | A footer linking both documents |
| `src/backend/assistant/views.py` | The consent gate at the chokepoint |
| `src/backend/finances/services/export_builder.py` | Four new `ledger.json` sections + `LEIA-ME.txt` (D11) |
| `src/backend/accounts/tests/test_tenancy_bases.py` | The `UsageInteraction.user` assertion this epic changes |
| `.env.example` | The four controller variables |
| `docs/runbook.md` | Purge job, data-subject-request procedure, breach procedure |
| `docs/backlog/E13-lgpd-compliance.md`, `docs/backlog/INDEX.md` | Status hygiene, and R3's gate |
| `src/backend/static/css/tailwind.css` | Rebuilt — new classes (Task 14) |

---

## Task 1: The processing inventory, and the test that keeps it honest

**Files:**
- Create: `src/backend/core/privacy/__init__.py`
- Create: `src/backend/core/privacy/inventory.py`
- Test: `src/backend/core/tests/test_privacy_inventory.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `core.privacy.Basis` — `StrEnum` with members `CONTRACT`, `CONSENT`, `LEGITIMATE`. `.article` gives the pt-BR LGPD citation.
  - `core.privacy.Disposal` — `StrEnum` with members `HOUSEHOLD`, `AUTHOR`, `CASCADE`, `ANONYMISE`, `SELF`, `NONE`.
  - `core.privacy.Record` — frozen dataclass: `label: str`, `purpose: str`, `basis: Basis | None`, `disposal: Disposal`, `retention_days: int | None`, `timestamp_field: str`, `subject_field: str`, `purge_filter: dict`.
  - `core.privacy.INVENTORY: tuple[Record, ...]` — one entry per model in the project.
  - `core.privacy.record_for(label: str) -> Record`.
  - `core.privacy.purgeable() -> list[Record]` — the subset with `retention_days is not None`.
  - `core.privacy.model_for(record: Record)` — the Django model class.

Tasks 6, 9, 10 and 11 all read this and nothing else.

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_privacy_inventory.py`:

```python
"""Every table in this product has a privacy decision attached to it.

This is the load-bearing test of E13. A model added later without an entry
here fails the suite, which is the only mechanism that keeps the privacy
notice a contract rather than a snapshot of one afternoon in August. Same idea
as `core/tests/test_metrics_doc.py`, and for the same reason.

`apps.get_models()` covers Django's own tables and allauth's too, deliberately:
`account.EmailAddress` and `mfa.Authenticator` hold personal data whether or
not we wrote them.
"""

import pytest
from django.apps import apps

from core.privacy import INVENTORY, Basis, Disposal, purgeable, record_for


def test_every_installed_model_is_classified():
    installed = {model._meta.label for model in apps.get_models()}
    classified = {record.label for record in INVENTORY}

    unclassified = installed - classified
    assert not unclassified, (
        "these models have no privacy decision — add a Record in "
        f"core/privacy/inventory.py: {sorted(unclassified)}"
    )


def test_the_inventory_names_no_model_that_does_not_exist():
    installed = {model._meta.label for model in apps.get_models()}
    ghosts = {record.label for record in INVENTORY} - installed
    assert not ghosts, f"the inventory names models that were deleted: {sorted(ghosts)}"


def test_no_label_is_listed_twice():
    labels = [record.label for record in INVENTORY]
    assert len(labels) == len(set(labels))


def test_every_author_record_names_a_column_that_actually_exists():
    """A typo here is a deletion that silently deletes nothing — the worst
    possible bug in this epic, because the receipt would still say it worked."""
    from django.conf import settings as django_settings

    user_label = django_settings.AUTH_USER_MODEL
    for record in INVENTORY:
        if record.disposal is not Disposal.AUTHOR:
            continue
        model = apps.get_model(record.label)
        field = model._meta.get_field(record.subject_field)
        assert field.related_model._meta.label_lower == user_label.lower(), (
            f"{record.label}.{record.subject_field} does not point at the user model"
        )


def test_exactly_one_record_is_the_person_themselves():
    selves = [r.label for r in INVENTORY if r.disposal is Disposal.SELF]
    assert selves == ["core.CustomUser"]


def test_every_record_that_holds_personal_data_states_a_lawful_basis():
    """Disposal NONE means "no personal data", and only then may basis be None.

    LGPD art. 7 requires a basis per purpose. A row that holds someone's data
    with no basis recorded is the violation, not the paperwork.
    """
    for record in INVENTORY:
        if record.disposal is Disposal.NONE:
            continue
        assert isinstance(record.basis, Basis), f"{record.label} has no lawful basis"


def test_every_record_has_a_purpose_written_in_portuguese_for_the_notice():
    for record in INVENTORY:
        assert record.purpose.strip(), f"{record.label} has no purpose"
        # The notice renders these verbatim. A purpose written in English would
        # ship an English sentence into a pt-BR legal document.
        assert not record.purpose.strip().startswith("TODO")


def test_every_purgeable_record_names_a_field_that_actually_exists():
    """A typo here is a purge that silently deletes nothing, forever."""
    for record in purgeable():
        model = apps.get_model(record.label)
        names = {field.name for field in model._meta.get_fields() if field.concrete}
        assert record.timestamp_field in names, (
            f"{record.label} would be purged on '{record.timestamp_field}', "
            "which is not a field on it"
        )


def test_every_purge_filter_is_a_valid_query_for_its_model():
    for record in purgeable():
        model = apps.get_model(record.label)
        # Evaluated lazily by Django, so `.query` is what forces validation
        # without touching the database.
        str(model._base_manager.filter(**record.purge_filter).query)


def test_the_chat_is_kept_for_ninety_days():
    """D2, asserted rather than trusted: the notice prints this number."""
    assert record_for("assistant.ChatMessage").retention_days == 90


def test_the_ledger_itself_is_never_purged_on_a_timer():
    """A user's entries are theirs until they delete the account. A retention
    period on the ledger would silently destroy the product."""
    for label in ("finances.Entry", "finances.Income", "finances.InstallmentPlan"):
        assert record_for(label).retention_days is None


def test_the_assistant_runs_on_consent_and_the_ledger_on_contract():
    """D3. If these ever disagree with the notice, the notice is a lie."""
    assert record_for("assistant.ChatMessage").basis is Basis.CONSENT
    assert record_for("assistant.MemoryRule").basis is Basis.CONSENT
    assert record_for("assistant.MemoryEmbedding").basis is Basis.CONSENT
    assert record_for("finances.Entry").basis is Basis.CONTRACT
    assert record_for("assistant.UsageRecord").basis is Basis.LEGITIMATE
    assert record_for("core.AdminAccessLog").basis is Basis.LEGITIMATE


def test_lawful_bases_cite_the_article_the_notice_prints():
    assert Basis.CONTRACT.article == "art. 7º, V"
    assert Basis.CONSENT.article == "art. 7º, I"
    assert Basis.LEGITIMATE.article == "art. 7º, IX"


@pytest.mark.parametrize(
    "label",
    [
        "assistant.ChatMessage",
        "assistant.MemoryRule",
        "assistant.ReceiptDraft",
        "core.Feedback",
    ],
)
def test_the_things_a_person_wrote_go_with_them(label):
    """D1: the household's ledger survives a member leaving; their own words
    do not."""
    assert record_for(label).disposal is Disposal.AUTHOR
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_privacy_inventory.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'core.privacy'`.

- [ ] **Step 3: Write the registry**

Create `src/backend/core/privacy/inventory.py`:

```python
"""What this product stores about people, why, and for how long.

The single list E13 is built on. Four things read it and nothing maintains a
copy:

  * ``core.privacy.deletion``  — what to do with a row when its author leaves
  * ``core.privacy.retention`` — what to delete on a timer
  * ``templates/legal/privacidade.html`` — the notice's purpose and retention
    tables, rendered from these rows rather than typed out beside them
  * ``core/tests/test_privacy_inventory.py`` — which fails when a model exists
    with no decision attached

That last one is the point. A privacy notice is only true on the day it is
written unless something forces it to keep up, and a list nobody is compelled
to update is the mechanism by which a compliant product quietly stops being one.

``purpose`` is pt-BR because it is rendered verbatim into a legal document that
Brazilians have to be able to read (S13-4). Everything else here is English,
like the rest of the codebase.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class Basis(StrEnum):
    """The lawful basis for a purpose. LGPD art. 7 defines ten; three apply.

    Decided in E13's brainstorm (plan decision D3) and confirmed by a lawyer
    before launch — this enum is engineering's record of the decision, not the
    legal opinion itself.
    """

    CONTRACT = "contrato"
    CONSENT = "consentimento"
    LEGITIMATE = "legitimo_interesse"

    @property
    def article(self) -> str:
        """The citation the notice prints next to each purpose."""
        return {
            Basis.CONTRACT: "art. 7º, V",
            Basis.CONSENT: "art. 7º, I",
            Basis.LEGITIMATE: "art. 7º, IX",
        }[self]

    @property
    def label(self) -> str:
        return {
            Basis.CONTRACT: "Execução de contrato",
            Basis.CONSENT: "Consentimento",
            Basis.LEGITIMATE: "Legítimo interesse",
        }[self]


class Disposal(StrEnum):
    """What happens to these rows when one member deletes their account (D1)."""

    #: Belongs to the household. Survives a member leaving; dies with the
    #: household when the last member goes, by the FK's own CASCADE.
    HOUSEHOLD = "household"
    #: The leaver's own rows are deleted, matched on ``created_by`` or ``user``.
    AUTHOR = "author"
    #: The database removes it when the user row goes. Nothing to do by hand.
    CASCADE = "cascade"
    #: Kept, with the user column set to NULL. Already how every ``created_by``
    #: behaves; listed explicitly for the rows we keep on purpose.
    ANONYMISE = "anonymise"
    #: The person themselves. Exactly one record carries this, and the deletion
    #: service does it last — a separate member rather than AUTHOR because
    #: "delete the rows this user wrote" and "delete this user" are different
    #: statements, and collapsing them would need a special case in the loop.
    SELF = "self"
    #: Holds no personal data at all — product configuration, reference tables.
    NONE = "none"


@dataclass(frozen=True)
class Record:
    """One model's privacy decision.

    ``timestamp_field`` and ``purge_filter`` exist only for ``retention_days``;
    ``subject_field`` only for ``Disposal.AUTHOR``. All three are on the record
    rather than in the services, because a service that knows something a model
    did not tell it is a second inventory.
    """

    label: str
    purpose: str
    basis: Basis | None
    disposal: Disposal
    retention_days: int | None = None
    timestamp_field: str = "created_at"
    #: Which column names the person, for AUTHOR rows. ``created_by`` on every
    #: ``AuthoredHouseholdModel``; ``core.Feedback`` calls it ``user``.
    subject_field: str = "created_by"
    purge_filter: dict = field(default_factory=dict)


#: Two years. Metering is what a bill is reconstructed from and what an abuse
#: claim is defended with, so it outlives the chat it measured.
_BILLING = 730

INVENTORY: tuple[Record, ...] = (
    # -- The ledger. The product itself, kept for as long as the account lives.
    Record(
        "finances.Entry",
        "Registrar seus gastos e receitas — o extrato que você veio usar.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "finances.Income",
        "Registrar sua renda, para projetar o mês.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "finances.Category",
        "Organizar os gastos por categoria.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "finances.PaymentMethod",
        "Saber em qual cartão ou conta cada gasto entrou, e em que mês ele fecha.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "finances.PaymentMethodClosingDay",
        "Guardar o dia de fechamento de um cartão num mês específico.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "finances.Budget",
        "Comparar o que foi gasto com o que foi planejado.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "finances.InstallmentPlan",
        "Acompanhar compras parceladas ao longo dos meses.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "finances.SystemicExpense",
        "Lembrar das despesas fixas que se repetem todo mês.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    # -- Jobs. The files themselves are deleted by a bucket lifecycle rule at 7
    #    days (D2a); these rows are the history of what happened.
    Record(
        "finances.ImportJob",
        "Mostrar o que aconteceu numa importação de CSV, inclusive as linhas "
        "que falharam — que trazem o texto original do seu arquivo.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
        # Only the abandoned ones. A finished import is the history page, and
        # docs/runbook.md says in as many words not to delete those.
        retention_days=180,
        purge_filter={"executed_at__isnull": True},
    ),
    Record(
        "finances.ExportJob",
        "Registrar quando você pediu uma cópia dos seus dados.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
        retention_days=180,
    ),
    # -- The assistant. Consent, and the shortest retention in the product.
    Record(
        "assistant.ChatMessage",
        "Manter o fio da conversa com o assistente. O conteúdo é enviado à "
        "OpenAI para ser processado.",
        Basis.CONSENT,
        Disposal.AUTHOR,
        retention_days=90,
    ),
    Record(
        "assistant.MemoryRule",
        "Lembrar suas correções — que 'cosmos' é mercado, por exemplo — para "
        "não errar a mesma categoria duas vezes.",
        Basis.CONSENT,
        Disposal.AUTHOR,
    ),
    Record(
        "assistant.MemoryEmbedding",
        "Encontrar a regra certa por semelhança de sentido. Vetores derivados "
        "das regras acima, calculados pela OpenAI.",
        Basis.CONSENT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "assistant.ReceiptDraft",
        "Guardar o que foi lido de um cupom até você confirmar ou descartar. "
        "A foto em si nunca é armazenada.",
        Basis.CONSENT,
        Disposal.AUTHOR,
        retention_days=90,
    ),
    # -- Metering. Legitimate interest: this is the bill and the abuse defence.
    Record(
        "assistant.UsageInteraction",
        "Contar quantos créditos cada uso do assistente custou.",
        Basis.LEGITIMATE,
        Disposal.ANONYMISE,
        retention_days=_BILLING,
    ),
    Record(
        "assistant.UsageRecord",
        "Registrar o custo real de cada chamada a um provedor de IA.",
        Basis.LEGITIMATE,
        Disposal.ANONYMISE,
        retention_days=_BILLING,
    ),
    # -- Tenancy and identity.
    Record(
        "core.CustomUser",
        "Sua conta: e-mail de acesso, senha (guardada como hash) e nome de exibição.",
        Basis.CONTRACT,
        Disposal.SELF,
    ),
    Record(
        "accounts.Household",
        "A casa cujas contas são compartilhadas.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    Record(
        "accounts.Membership",
        "Quem tem acesso a qual casa, e com qual papel.",
        Basis.CONTRACT,
        Disposal.CASCADE,
    ),
    Record(
        "accounts.Invitation",
        "Um convite pendente para alguém entrar na casa. Guarda o e-mail "
        "convidado até o convite ser aceito, cancelado ou vencer.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
        retention_days=180,
    ),
    Record(
        "accounts.OnboardingState",
        "Até onde a casa chegou na configuração inicial.",
        Basis.CONTRACT,
        Disposal.HOUSEHOLD,
    ),
    # `core.PolicyAcceptance` and `core.Consent` are added here by Task 2, in
    # the same commit that creates them. Adding them now would make this file's
    # own completeness test fail on models that do not exist yet.
    Record(
        "account.EmailAddress",
        "Confirmar que o endereço de e-mail é seu.",
        Basis.CONTRACT,
        Disposal.CASCADE,
    ),
    Record(
        "account.EmailConfirmation",
        "Um link de confirmação de e-mail, de curta duração.",
        Basis.CONTRACT,
        Disposal.CASCADE,
    ),
    Record(
        "mfa.Authenticator",
        "A chave da sua verificação em duas etapas e os códigos de recuperação.",
        Basis.CONTRACT,
        Disposal.CASCADE,
    ),
    Record(
        "sessions.Session",
        "Manter você conectado entre uma página e outra.",
        Basis.CONTRACT,
        Disposal.ANONYMISE,
        # Zero days on `expire_date`: delete every session already expired.
        # This is `clearsessions` semantics, folded into the one job that runs.
        retention_days=0,
        timestamp_field="expire_date",
    ),
    # -- Security and abuse. Legitimate interest, and none of it is content.
    Record(
        "core.LoginAttempt",
        "Contar tentativas de login que falharam, para bloquear ataques de força bruta.",
        Basis.LEGITIMATE,
        Disposal.ANONYMISE,
        retention_days=30,
    ),
    Record(
        "core.AdminAccessLog",
        "Registrar quando um administrador abriu uma página que mostra dados "
        "de clientes.",
        Basis.LEGITIMATE,
        Disposal.ANONYMISE,
        retention_days=_BILLING,
    ),
    Record(
        "admin.LogEntry",
        "Registro do Django sobre o que um administrador alterou no painel.",
        Basis.LEGITIMATE,
        Disposal.CASCADE,
        retention_days=_BILLING,
        timestamp_field="action_time",
    ),
    # -- Product analytics. No user content, by construction.
    Record(
        "core.ProductEvent",
        "Contar passos do produto — cadastro, primeira foto, ativação. "
        "Nunca guarda o que você escreveu.",
        Basis.LEGITIMATE,
        Disposal.ANONYMISE,
        retention_days=_BILLING,
    ),
    Record(
        "core.Feedback",
        "O que você escreveu ao mandar um comentário sobre o produto.",
        Basis.LEGITIMATE,
        Disposal.AUTHOR,
        retention_days=_BILLING,
        # Not `created_by`: this model names the person `user`.
        subject_field="user",
    ),
    # -- Infrastructure and reference data. No personal data in any of these.
    Record(
        "core.TaskRun",
        "Fila de trabalhos em segundo plano. Guarda identificadores, nunca conteúdo.",
        None,
        Disposal.NONE,
        retention_days=90,
    ),
    Record(
        "accounts.Plan",
        "Os planos disponíveis. Igual para todo mundo.",
        None,
        Disposal.NONE,
    ),
    Record(
        "assistant.ModelPrice",
        "Tabela de preços dos modelos de IA. Igual para todo mundo.",
        None,
        Disposal.NONE,
    ),
    Record(
        "assistant.CreditPrice",
        "Quantos créditos custa cada tipo de uso. Igual para todo mundo.",
        None,
        Disposal.NONE,
    ),
    Record("auth.Group", "Grupos de permissão do Django.", None, Disposal.NONE),
    Record("auth.Permission", "Permissões do Django.", None, Disposal.NONE),
    Record(
        "contenttypes.ContentType",
        "Tabela interna do Django que nomeia os outros modelos.",
        None,
        Disposal.NONE,
    ),
)

_BY_LABEL = {record.label: record for record in INVENTORY}


def record_for(label: str) -> Record:
    """The decision for one model. ``KeyError`` when there is none — which is
    the same thing the completeness test says, only later."""
    return _BY_LABEL[label]


def purgeable() -> list[Record]:
    """The records the retention job walks."""
    return [record for record in INVENTORY if record.retention_days is not None]


def model_for(record: Record):
    """The Django model class a record names."""
    from django.apps import apps

    return apps.get_model(record.label)
```

- [ ] **Step 4: Write the package's public surface**

Create `src/backend/core/privacy/__init__.py`:

```python
"""What the product knows about people, and what it does about that.

The public surface is deliberately small, the same discipline as
``core.tasks``: everything else in this package is internal, so the inventory
cannot be bypassed by importing something one layer down and writing a second
list of models.
"""

from core.privacy.inventory import (
    INVENTORY,
    Basis,
    Disposal,
    Record,
    model_for,
    purgeable,
    record_for,
)

__all__ = [
    "INVENTORY",
    "Basis",
    "Disposal",
    "Record",
    "model_for",
    "purgeable",
    "record_for",
]
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_privacy_inventory.py -q
```

Expected: 14 passed. Every model that exists at `65a1c7d` has an entry; nothing in the inventory names a model that does not exist. Task 2's two new models will fail `test_every_installed_model_is_classified` the moment they are created, which is the mechanism working exactly as designed — Task 2 adds their records in the same commit.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/core/privacy/ src/backend/core/tests/test_privacy_inventory.py
git commit -m "feat(E13): the processing inventory, and the test that keeps it complete"
```

---

## Task 2: `PolicyAcceptance` and `Consent`

**Files:**
- Modify: `src/backend/core/models.py`
- Modify: `src/backend/core/privacy/inventory.py`
- Create: `src/backend/core/privacy/consent.py`
- Modify: `src/backend/config/settings.py`
- Modify: `.env.example`
- Create: `src/backend/core/migrations/00XX_policy_acceptance_and_consent.py` (generated)
- Test: `src/backend/core/tests/test_privacy_consent.py`

**Interfaces:**
- Consumes: `core.privacy.Record`, `Basis`, `Disposal` (Task 1).
- Produces:
  - `core.models.PolicyDocument` — `TextChoices`, members `PRIVACY = "privacy"`, `TERMS = "terms"`.
  - `core.models.PolicyAcceptance` — fields `user`, `document`, `version`, `accepted_at`, `ip`. Unique on `(user, document, version)`.
  - `core.models.ConsentPurpose` — `TextChoices`, one member `AI_ASSISTANT = "ai_assistant"`.
  - `core.models.Consent` — fields `user`, `purpose`, `granted`, `granted_at`, `revoked_at`, `updated_at`. Unique on `(user, purpose)`.
  - `core.privacy.consent.has_ai_consent(user) -> bool`.
  - `core.privacy.consent.ahas_ai_consent(user) -> bool` — the async form `assistant/views.py` needs.
  - `core.privacy.consent.set_ai_consent(user, *, granted: bool) -> Consent`.
  - `core.privacy.consent.AI_CONSENT_REQUIRED` — the pt-BR message the chat returns.
  - `settings.PRIVACY_POLICY_VERSION`, `settings.TERMS_VERSION` — date strings.

Task 3 writes acceptance rows. Task 4 gates on consent. Task 7 renders both. Task 11 renders the version.

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_privacy_consent.py`:

```python
"""Consent for the AI leg, and the record that a policy version was accepted.

The assistant runs on consent (plan decision D3), which is only true if it can
be withheld and taken back. These tests are what stops that becoming a sentence
in a document with no code behind it.
"""

from datetime import UTC, datetime

import pytest
from django.conf import settings
from django.db import IntegrityError
from model_bakery import baker

from core.models import Consent, ConsentPurpose, PolicyAcceptance, PolicyDocument
from core.privacy.consent import has_ai_consent, set_ai_consent

pytestmark = pytest.mark.django_db

FROZEN_NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


class TestAIConsent:
    def test_a_new_account_has_not_consented(self):
        """Absence is a refusal. Defaulting to granted would make the whole
        mechanism decorative."""
        person = baker.make("core.CustomUser", email="nova@example.com")
        assert has_ai_consent(person) is False

    def test_granting_it_is_recorded_with_the_moment_it_happened(self, time_machine):
        time_machine.move_to(FROZEN_NOW, tick=False)
        person = baker.make("core.CustomUser", email="vagner@example.com")

        consent = set_ai_consent(person, granted=True)

        assert has_ai_consent(person) is True
        assert consent.granted is True
        assert consent.granted_at == FROZEN_NOW
        assert consent.revoked_at is None

    def test_revoking_it_keeps_the_row_and_stamps_the_revocation(self, time_machine):
        """The row is not deleted: 'they consented on the 17th and withdrew on
        the 20th' is the evidence an ANPD question asks for, and a deleted row
        cannot answer it."""
        time_machine.move_to(FROZEN_NOW, tick=False)
        person = baker.make("core.CustomUser", email="vagner@example.com")
        set_ai_consent(person, granted=True)

        time_machine.move_to(datetime(2026, 8, 20, 12, 0, tzinfo=UTC), tick=False)
        consent = set_ai_consent(person, granted=False)

        assert has_ai_consent(person) is False
        assert consent.granted is False
        assert consent.granted_at == FROZEN_NOW
        assert consent.revoked_at == datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

    def test_granting_again_after_a_revocation_clears_the_revocation(self, time_machine):
        time_machine.move_to(FROZEN_NOW, tick=False)
        person = baker.make("core.CustomUser", email="vagner@example.com")
        set_ai_consent(person, granted=True)
        set_ai_consent(person, granted=False)

        consent = set_ai_consent(person, granted=True)

        assert has_ai_consent(person) is True
        assert consent.revoked_at is None

    def test_one_row_per_person_per_purpose(self):
        person = baker.make("core.CustomUser", email="vagner@example.com")
        set_ai_consent(person, granted=True)
        set_ai_consent(person, granted=False)
        set_ai_consent(person, granted=True)

        assert Consent.objects.filter(user=person).count() == 1

    def test_the_database_refuses_a_second_row_for_the_same_purpose(self):
        person = baker.make("core.CustomUser", email="vagner@example.com")
        Consent.objects.create(user=person, purpose=ConsentPurpose.AI_ASSISTANT, granted=True)
        with pytest.raises(IntegrityError):
            Consent.objects.create(user=person, purpose=ConsentPurpose.AI_ASSISTANT, granted=True)

    def test_one_persons_consent_is_not_anothers(self):
        alice = baker.make("core.CustomUser", email="alice@example.com")
        bruno = baker.make("core.CustomUser", email="bruno@example.com")
        set_ai_consent(alice, granted=True)
        assert has_ai_consent(bruno) is False

    def test_an_anonymous_visitor_has_not_consented(self):
        """`has_ai_consent` is called from a view that has already checked
        authentication, but a permission helper that raises on absent input
        becomes a 500 on the exact request that should have been a 403 — the
        same rule `accounts.permissions.is_owner` follows."""
        from django.contrib.auth.models import AnonymousUser

        assert has_ai_consent(AnonymousUser()) is False
        assert has_ai_consent(None) is False


class TestPolicyAcceptance:
    def test_an_acceptance_records_the_document_the_version_and_the_moment(self, time_machine):
        time_machine.move_to(FROZEN_NOW, tick=False)
        person = baker.make("core.CustomUser", email="vagner@example.com")

        acceptance = PolicyAcceptance.objects.create(
            user=person,
            document=PolicyDocument.PRIVACY,
            version=settings.PRIVACY_POLICY_VERSION,
            ip="203.0.113.7",
        )

        assert acceptance.accepted_at == FROZEN_NOW
        assert acceptance.version == settings.PRIVACY_POLICY_VERSION

    def test_the_same_version_cannot_be_accepted_twice(self):
        """Idempotence at the database, so a double-submitted signup form
        cannot write two rows and make 'when did they accept?' ambiguous."""
        person = baker.make("core.CustomUser", email="vagner@example.com")
        PolicyAcceptance.objects.create(
            user=person, document=PolicyDocument.TERMS, version="2026-08-17"
        )
        with pytest.raises(IntegrityError):
            PolicyAcceptance.objects.create(
                user=person, document=PolicyDocument.TERMS, version="2026-08-17"
            )

    def test_a_new_version_is_a_new_row_rather_than_an_update(self):
        person = baker.make("core.CustomUser", email="vagner@example.com")
        PolicyAcceptance.objects.create(
            user=person, document=PolicyDocument.TERMS, version="2026-08-17"
        )
        PolicyAcceptance.objects.create(
            user=person, document=PolicyDocument.TERMS, version="2027-01-04"
        )
        assert PolicyAcceptance.objects.filter(user=person).count() == 2


class TestTheVersionsAreConfigured:
    def test_both_documents_carry_a_version(self):
        """Blank versions would record an acceptance of nothing in particular."""
        assert settings.PRIVACY_POLICY_VERSION.strip()
        assert settings.TERMS_VERSION.strip()

    def test_the_versions_are_dates_so_a_human_can_order_them(self):
        from datetime import date

        date.fromisoformat(settings.PRIVACY_POLICY_VERSION)
        date.fromisoformat(settings.TERMS_VERSION)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_privacy_consent.py -q
```

Expected: FAIL — `ImportError: cannot import name 'Consent' from 'core.models'`.

- [ ] **Step 3: Write the models**

Append to `src/backend/core/models.py`:

```python
class PolicyDocument(models.TextChoices):
    """The two documents a person accepts to use this product."""

    PRIVACY = "privacy", "Aviso de privacidade"
    TERMS = "terms", "Termos de uso"


class PolicyAcceptance(models.Model):
    """Proof that a specific person accepted a specific version, on a date.

    Versioned rather than a boolean on the user, because "did they accept the
    terms?" is not the question anyone will actually ask. The question is
    "which terms did they accept?", and a boolean cannot answer it after the
    first amendment.

    CASCADE, unlike most user foreign keys here: an acceptance is a statement
    about a person, so it has no meaning once that person is gone. The
    household's ledger survives a deletion (E04's SET_NULL rule); this does not,
    and should not.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="policy_acceptances"
    )
    document = models.CharField(max_length=20, choices=PolicyDocument.choices)
    version = models.CharField(max_length=20)
    accepted_at = models.DateTimeField(auto_now_add=True)
    # Kept because an acceptance without any circumstance around it is weak
    # evidence. Nothing else is: no user agent, no fingerprint.
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "aceite de política"
        verbose_name_plural = "aceites de política"
        ordering = ["-accepted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "document", "version"], name="one_acceptance_per_version"
            )
        ]

    def __str__(self):
        return f"{self.user} aceitou {self.document} {self.version}"


class ConsentPurpose(models.TextChoices):
    """Purposes that run on consent rather than on contract.

    Exactly one today. It is an enum rather than a boolean because the second
    one — analytics shipped to a vendor, say — must not require a migration and
    a rewrite of every call site to add.
    """

    AI_ASSISTANT = "ai_assistant", "Assistente de IA"


class Consent(models.Model):
    """Whether this person has authorised a purpose, and when they changed it.

    One row per person per purpose, updated in place, with both timestamps kept.
    Deleting the row on revocation would be the obvious implementation and the
    wrong one: "they consented on the 17th and withdrew on the 20th" is exactly
    what a data-subject complaint asks about, and a deleted row cannot say it.

    Absence means "not granted". LGPD art. 8 wants consent to be an affirmative
    act, so a default of True would not be consent at all.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="consents"
    )
    purpose = models.CharField(max_length=30, choices=ConsentPurpose.choices)
    granted = models.BooleanField(default=False)
    granted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "consentimento"
        verbose_name_plural = "consentimentos"
        constraints = [
            models.UniqueConstraint(fields=["user", "purpose"], name="one_consent_per_purpose")
        ]

    def __str__(self):
        state = "concedido" if self.granted else "recusado"
        return f"{self.user}: {self.purpose} {state}"
```

- [ ] **Step 4: Write the consent service**

Create `src/backend/core/privacy/consent.py`:

```python
"""Asking, recording and honouring consent for the AI leg.

The product's core — the ledger — runs on execução de contrato and needs no
permission beyond signing up. The assistant does not: it sends what a person
writes, says and photographs to OpenAI, and plan decision D3 puts that on
consentimento (LGPD art. 7º, I).

Which means it has to be refusable. This module is the whole of that: one
boolean, asked at the chat chokepoint, flipped from the Privacidade tab.
"""

from django.utils import timezone

from core.models import Consent, ConsentPurpose

#: What the assistant answers when consent is absent. Rendered by the chat
#: widget as the assistant's own reply — `ChatWidget.tsx` reads `{error}` off
#: any non-OK response — so it is written as a sentence to a person, not as an
#: error code.
AI_CONSENT_REQUIRED = (
    "Para usar o assistente eu preciso da sua autorização para enviar o que "
    "você escreve, fala ou fotografa à OpenAI, que é quem processa isso. "
    "Você autoriza em Conta → Privacidade, e pode voltar atrás quando quiser. "
    "O resto do aplicativo funciona normalmente sem isso."
)


def has_ai_consent(user) -> bool:
    """True when ``user`` has authorised the AI processing.

    Fails closed on every missing input — an anonymous visitor, ``None``, a
    user with no row — because a consent check that raises turns the request it
    was meant to refuse into a 500. Same rule as ``accounts.permissions.is_owner``.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return Consent.objects.filter(
        user=user, purpose=ConsentPurpose.AI_ASSISTANT, granted=True
    ).exists()


async def ahas_ai_consent(user) -> bool:
    """The async form. ``assistant.views.chat_view`` is async and resolves its
    user with ``aget_user``, so it cannot call the sync one."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return await Consent.objects.filter(
        user=user, purpose=ConsentPurpose.AI_ASSISTANT, granted=True
    ).aexists()


def set_ai_consent(user, *, granted: bool) -> Consent:
    """Record a decision, keeping both timestamps.

    ``granted_at`` survives a revocation on purpose: the pair of dates is the
    evidence, and overwriting the first one would destroy half of it.
    """
    now = timezone.now()
    consent, _ = Consent.objects.get_or_create(
        user=user, purpose=ConsentPurpose.AI_ASSISTANT
    )
    consent.granted = granted
    if granted:
        consent.granted_at = now
        consent.revoked_at = None
    else:
        consent.revoked_at = now
    consent.save(update_fields=["granted", "granted_at", "revoked_at", "updated_at"])
    return consent
```

- [ ] **Step 5: Export it from the package**

In `src/backend/core/privacy/__init__.py`, extend the imports and `__all__`:

```python
from core.privacy.consent import (
    AI_CONSENT_REQUIRED,
    ahas_ai_consent,
    has_ai_consent,
    set_ai_consent,
)
from core.privacy.inventory import (
    INVENTORY,
    Basis,
    Disposal,
    Record,
    model_for,
    purgeable,
    record_for,
)

__all__ = [
    "AI_CONSENT_REQUIRED",
    "INVENTORY",
    "Basis",
    "Disposal",
    "Record",
    "ahas_ai_consent",
    "has_ai_consent",
    "model_for",
    "purgeable",
    "record_for",
    "set_ai_consent",
]
```

- [ ] **Step 6: Add the two records to the inventory**

In `src/backend/core/privacy/inventory.py`, replace the `# core.PolicyAcceptance and core.Consent are added here by Task 2` comment with:

```python
    Record(
        "core.PolicyAcceptance",
        "Provar que você aceitou uma versão específica dos termos e do aviso "
        "de privacidade, e quando.",
        Basis.LEGITIMATE,
        Disposal.CASCADE,
    ),
    Record(
        "core.Consent",
        "Guardar se você autorizou o processamento por IA, e quando mudou de ideia.",
        Basis.LEGITIMATE,
        Disposal.CASCADE,
    ),
```

- [ ] **Step 7: Add the document versions to settings**

In `src/backend/config/settings.py`, after the allauth block (near line 314), add:

```python
# --- Privacy and terms (E13) --------------------------------------------
#
# Dates, not integers: a version a person can compare with the day they signed
# up is worth more than a counter nobody can place in time. Bump these in the
# same commit that changes the document, or `PolicyAcceptance` records an
# acceptance of text nobody can reconstruct.
PRIVACY_POLICY_VERSION = os.environ.get("PRIVACY_POLICY_VERSION", "2026-08-17")
TERMS_VERSION = os.environ.get("TERMS_VERSION", "2026-08-17")
```

- [ ] **Step 8: Generate and inspect the migration**

```bash
uv run python src/backend/manage.py makemigrations core \
  -n policy_acceptance_and_consent
```

Open the generated file and confirm it contains exactly two `CreateModel`
operations and their two `AddConstraint`s, and no `AlterField` on anything
else. A migration for `core` that touches `CustomUser` means something was
edited that should not have been — stop and fix it here.

```bash
uv run python src/backend/manage.py migrate core
uv run python src/backend/manage.py makemigrations --check --dry-run
```

Expected: `No changes detected`.

- [ ] **Step 9: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_privacy_consent.py -q
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_privacy_inventory.py -q
```

Expected: both green. The inventory test is the one that matters — it proves the two new models did not slip in without a decision.

- [ ] **Step 10: Update `.env.example`**

Under a new `# --- Privacy (E13) ---` heading:

```
# Bump in the same commit that changes the document text. Recorded on every
# signup as the version that person accepted.
PRIVACY_POLICY_VERSION=2026-08-17
TERMS_VERSION=2026-08-17
```

- [ ] **Step 11: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/core/models.py src/backend/core/migrations/ \
        src/backend/core/privacy/ src/backend/config/settings.py \
        src/backend/core/tests/test_privacy_consent.py .env.example
git commit -m "feat(E13): policy acceptance and revocable consent for the AI leg"
```

---

## Task 3: Signup records which version was accepted

**Files:**
- Create: `src/backend/accounts/forms_signup.py`
- Modify: `src/backend/config/settings.py`
- Modify: `src/backend/templates/account/signup.html`
- Test: `src/backend/accounts/tests/test_signup_records_acceptance.py`

**Interfaces:**
- Consumes: `core.models.PolicyAcceptance`, `PolicyDocument` (Task 2); `settings.PRIVACY_POLICY_VERSION`, `settings.TERMS_VERSION`.
- Produces: `accounts.forms_signup.LedgerSignupForm` — a `forms.Form` with one field, `accept_terms: BooleanField(required=True)`, and a `signup(self, request, user)` method. Registered through `ACCOUNT_SIGNUP_FORM_CLASS`.

`ACCOUNT_SIGNUP_FORM_CLASS` is allauth 65.19.1's supported extension point: the named class becomes the **base** of `BaseSignupForm` (`allauth/account/internal/flows/signup.py:28-41`), and its `signup(request, user)` is invoked from `SignupForm.save` **after** `adapter.save_user`, so the user already has a primary key (`allauth/account/forms.py:417-427`). Do not subclass `allauth.account.forms.SignupForm` — that produces a recursive base and fails at import.

- [ ] **Step 1: Run the daisyUI Blueprint chain, steps 1–4**

`workflowId: e13-signup`, `projectRoot: /home/bessa/Documents/projetos/expense_tracker_v2`, `install: false`. Setup Expert → Rules Enforcer → Component Syntax Expert for: `checkbox`, `label`, `fieldset`, `link`, `alert`. Skip Creative Director and Page Architect.

- [ ] **Step 2: Write the failing test**

Create `src/backend/accounts/tests/test_signup_records_acceptance.py`:

```python
"""Signing up records *which* documents were accepted, and which version.

The DoD asks for "signup records acceptance of a specific policy version".
Specific is the whole requirement: a boolean would satisfy a checkbox on a
form and nothing a regulator would ask for.
"""

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from core.models import PolicyAcceptance, PolicyDocument

pytestmark = pytest.mark.django_db

GOOD = {
    "email": "nova@example.com",
    "email2": "nova@example.com",
    "password1": "uma-senha-bem-comprida-7",
    "password2": "uma-senha-bem-comprida-7",
}


def test_signing_up_records_both_documents_at_their_current_versions():
    response = Client().post(reverse("account_signup"), {**GOOD, "accept_terms": "on"})
    assert response.status_code in (200, 302)

    accepted = {
        (row.document, row.version)
        for row in PolicyAcceptance.objects.filter(user__email="nova@example.com")
    }
    assert accepted == {
        (PolicyDocument.PRIVACY, settings.PRIVACY_POLICY_VERSION),
        (PolicyDocument.TERMS, settings.TERMS_VERSION),
    }


def test_the_checkbox_is_required_and_no_account_is_created_without_it():
    from core.models import CustomUser

    response = Client().post(reverse("account_signup"), GOOD)

    assert response.status_code == 200  # re-rendered with an error, not a redirect
    assert not CustomUser.objects.filter(email="nova@example.com").exists()
    assert not PolicyAcceptance.objects.exists()


def test_the_error_is_in_portuguese():
    response = Client().post(reverse("account_signup"), GOOD)
    body = response.content.decode()
    assert "Termos de Uso" in body or "aceitar" in body.lower()


def test_the_signup_page_links_both_documents_so_they_can_be_read_first():
    """An acceptance of a document with no link to it is not informed consent."""
    body = Client().get(reverse("account_signup")).content.decode()
    assert reverse("privacy_notice") in body
    assert reverse("terms_of_service") in body


def test_the_ip_is_recorded():
    Client().post(
        reverse("account_signup"),
        {**GOOD, "accept_terms": "on"},
        REMOTE_ADDR="203.0.113.7",
    )
    rows = PolicyAcceptance.objects.filter(user__email="nova@example.com")
    assert {row.ip for row in rows} == {"203.0.113.7"}


def test_signing_up_does_not_grant_ai_consent():
    """Plan decision D3b: the AI ask happens in context, at first use. Bundling
    it into this checkbox would make it neither specific nor informed."""
    from core.privacy import has_ai_consent
    from core.models import CustomUser

    Client().post(reverse("account_signup"), {**GOOD, "accept_terms": "on"})
    person = CustomUser.objects.get(email="nova@example.com")
    assert has_ai_consent(person) is False


def test_the_existing_signup_side_effects_still_happen():
    """E04 seeds a household on signup and E14 emits the `signup` event. This
    form sits in the middle of that flow, so it is worth asserting it did not
    displace either."""
    from accounts.models import Membership
    from core.events import EventName
    from core.models import CustomUser, ProductEvent

    Client().post(reverse("account_signup"), {**GOOD, "accept_terms": "on"})

    person = CustomUser.objects.get(email="nova@example.com")
    assert Membership.objects.filter(user=person).exists()
    assert ProductEvent.objects.filter(name=EventName.SIGNUP).exists()
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_signup_records_acceptance.py -q
```

Expected: FAIL — `NoReverseMatch: Reverse for 'privacy_notice' not found` on some, and the acceptance assertions failing with an empty set on the rest. Task 11 creates those two URL names; the two tests that reverse them stay red until then, and that is stated in Step 6 below.

- [ ] **Step 4: Write the form**

Create `src/backend/accounts/forms_signup.py`:

```python
"""The one thing E13 adds to the signup form.

Wired through ``ACCOUNT_SIGNUP_FORM_CLASS`` rather than by replacing allauth's
form: allauth makes the named class the *base* of both its local and its social
signup forms (``allauth/account/internal/flows/signup.py``), so this is the
extension point that does not fork a security-critical flow. Subclassing
``allauth.account.forms.SignupForm`` here would make it its own base and fail
at import.

``signup`` runs after ``adapter.save_user``, so ``user`` already has a primary
key — which is why the acceptance rows can be written straight in.
"""

from django import forms
from django.conf import settings

from core.models import PolicyAcceptance, PolicyDocument


def client_ip(request) -> str | None:
    """The caller's address as Cloud Run reports it.

    Cloud Run terminates TLS at the front end and puts the real client first in
    ``X-Forwarded-For``; ``REMOTE_ADDR`` is the proxy. Taking the first element
    is right here and would be wrong for rate limiting, where a spoofed header
    is the attack — this value is evidence attached to a consent, not a control.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


class LedgerSignupForm(forms.Form):
    """One required checkbox, and the two rows it produces."""

    accept_terms = forms.BooleanField(
        required=True,
        label="Li e aceito os Termos de Uso e o Aviso de Privacidade",
        error_messages={
            "required": "Para criar a conta é preciso aceitar os Termos de Uso "
            "e o Aviso de Privacidade."
        },
    )

    def signup(self, request, user) -> None:
        """Record what was accepted, at the version live right now.

        Two rows rather than one: the documents are versioned independently, so
        a change to the terms must not silently claim a fresh acceptance of the
        privacy notice.
        """
        ip = client_ip(request)
        PolicyAcceptance.objects.bulk_create(
            [
                PolicyAcceptance(
                    user=user,
                    document=PolicyDocument.PRIVACY,
                    version=settings.PRIVACY_POLICY_VERSION,
                    ip=ip,
                ),
                PolicyAcceptance(
                    user=user,
                    document=PolicyDocument.TERMS,
                    version=settings.TERMS_VERSION,
                    ip=ip,
                ),
            ],
            # A retried signup must not 500 on the unique constraint.
            ignore_conflicts=True,
        )
```

- [ ] **Step 5: Point allauth at it**

In `src/backend/config/settings.py`, beside `ACCOUNT_ADAPTER` (line 298):

```python
# E13: the terms checkbox, and the PolicyAcceptance rows it writes. This is
# allauth's supported extension point — the class becomes the base of both the
# local and the social signup form, so nothing about the flow itself is forked.
ACCOUNT_SIGNUP_FORM_CLASS = "accounts.forms_signup.LedgerSignupForm"
```

- [ ] **Step 6: Add the checkbox to the signup template**

In `src/backend/templates/account/signup.html`, immediately after the closing `</fieldset>` and before the `{% if redirect_field_value %}` block:

```html
    {# E13. Required, and the links are not decoration: an acceptance of a #}
    {# document the person had no way to read is not informed consent.     #}
    <fieldset class="fieldset mt-2">
        <label class="label cursor-pointer justify-start gap-3 items-start">
            <input type="checkbox" name="accept_terms" id="id_accept_terms"
                   class="checkbox checkbox-sm mt-0.5
                          {% if form.accept_terms.errors %}checkbox-error{% endif %}"
                   {% if form.accept_terms.value %}checked{% endif %} required>
            <span class="text-sm leading-snug">
                Li e aceito os
                <a href="{% url 'terms_of_service' %}" target="_blank" class="link">Termos de Uso</a>
                e o
                <a href="{% url 'privacy_notice' %}" target="_blank" class="link">Aviso de Privacidade</a>.
            </span>
        </label>
        {% if form.accept_terms.errors %}
        <p class="label text-error">{{ form.accept_terms.errors|first }}</p>
        {% endif %}
    </fieldset>
```

- [ ] **Step 7: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_signup_records_acceptance.py -q
```

Expected: **five passed, two failed** — `test_the_signup_page_links_both_documents_so_they_can_be_read_first` and every test that renders the template fail with `NoReverseMatch: Reverse for 'privacy_notice' not found`, because Task 11 has not registered those URLs yet.

That is a genuine ordering dependency and this plan resolves it by **doing Task 11 before this task's commit is considered green**. If you are executing tasks in order, take the two-line URL stub from Task 11 Step 5 now:

```python
    path("privacidade/", PrivacyNoticeView.as_view(), name="privacy_notice"),
    path("termos/", TermsView.as_view(), name="terms_of_service"),
```

…with placeholder templates, and let Task 11 fill the documents in. Re-run:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_signup_records_acceptance.py -q
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/ -q
```

Expected: 7 passed, and the whole `accounts` suite still green — the signup flow is exercised by `test_signup_creates_household.py`, `test_signup_emits_event.py` and `test_invited_signup.py`, all of which now post through a form with a new required field. **If those go red, they need `"accept_terms": "on"` added to their POST payloads — that is a correct change, not a workaround.** Make it.

- [ ] **Step 8: Run the Quality Inspector**

`daisyui_quality_inspector`, `workflowId: e13-signup`, `auditIntent: "fix_changes"`, file `src/backend/templates/account/signup.html`, line range from `git diff --unified=0`.

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/accounts/forms_signup.py src/backend/config/settings.py \
        src/backend/templates/account/signup.html \
        src/backend/accounts/tests/
git commit -m "feat(E13): signup records which policy version was accepted"
```

---

## Task 4: The assistant refuses without consent

**Files:**
- Modify: `src/backend/assistant/views.py`
- Test: `src/backend/assistant/tests/test_ai_consent_gate.py` (create)

**Interfaces:**
- Consumes: `core.privacy.ahas_ai_consent`, `core.privacy.AI_CONSENT_REQUIRED` (Task 2).
- Produces: nothing new. `POST /api/assistant/chat/` gains a `403` with `{"error": "<pt-BR sentence>"}` when consent is absent.

**No front-end change.** `ChatWidget.tsx:53-58` reads `data.error` off any non-OK response and `:471-474` renders it as the assistant's own message. A 403 with a sentence is therefore already a well-formed answer in the UI, and `mount.js` does not need rebuilding.

The gate goes **before** `decide(...)` (`assistant/views.py:296`), not after: a person who has not consented must not have an interaction opened, credits charged, or a `UsageInteraction` row written about them.

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_ai_consent_gate.py`:

```python
"""The assistant is the one part of this product that runs on consent.

Plan decision D3 puts chat, memory and receipt OCR on LGPD art. 7º, I. That is
only true if the answer to "no" is an actual refusal, and if refusing costs the
person nothing — no credits, no metering row, no record of an interaction they
did not have.
"""

import json

import pytest
from django.test import Client
from django.urls import reverse

from core.privacy import set_ai_consent

pytestmark = pytest.mark.django_db


def post_chat(client, message="oi"):
    return client.post(
        reverse("assistant:chat"),
        data=json.dumps({"message": message}),
        content_type="application/json",
    )


class TestTheGate:
    def test_without_consent_the_assistant_refuses(self, logged_client):
        response = post_chat(logged_client)
        assert response.status_code == 403

    def test_the_refusal_explains_itself_in_portuguese_and_says_where_to_fix_it(
        self, logged_client
    ):
        """The widget renders `error` as the assistant's reply, so this string
        is the user interface — not a log line."""
        body = post_chat(logged_client).json()
        assert "OpenAI" in body["error"]
        assert "Privacidade" in body["error"]

    def test_refusing_costs_nothing(self, logged_client, household):
        """No interaction, no usage row, no chat message. A refusal that still
        charged for itself would be worse than no gate at all."""
        from assistant.models import ChatMessage, UsageInteraction, UsageRecord

        post_chat(logged_client)

        assert not UsageInteraction.objects.filter(household=household).exists()
        assert not UsageRecord.objects.filter(household=household).exists()
        assert not ChatMessage.objects.filter(household=household).exists()

    def test_with_consent_the_gate_lets_the_request_through(self, logged_client, user):
        """Past the gate, not past everything — the reply itself needs a model,
        which the suite refuses to call. Anything other than 403 proves the gate
        opened, and that is what this test is about."""
        set_ai_consent(user, granted=True)
        response = post_chat(logged_client)
        assert response.status_code != 403

    def test_revoking_closes_it_again(self, logged_client, user):
        set_ai_consent(user, granted=True)
        set_ai_consent(user, granted=False)
        assert post_chat(logged_client).status_code == 403

    def test_an_unauthenticated_caller_still_gets_403_for_being_unauthenticated(self):
        """The order matters: authentication first, then consent. Reversing it
        would let a stranger probe whether an account exists."""
        response = post_chat(Client())
        assert response.status_code == 403


class TestWhatIsNotGated:
    def test_reading_your_own_history_is_not_gated(self, logged_client, user):
        """History is the access right (S13-2). Refusing someone their own data
        because they withdrew consent to *future* processing would be the
        opposite of what consent is for."""
        set_ai_consent(user, granted=False)
        response = logged_client.get(reverse("assistant:history"))
        assert response.status_code == 200

    def test_the_ledger_still_works_without_consent(self, logged_client):
        """Contract, not consent (D3). If withdrawing consent broke the
        bookkeeping, the notice's claim that the product works without the
        assistant would be false."""
        response = logged_client.get("/")
        assert response.status_code == 200
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_ai_consent_gate.py -q
```

Expected: FAIL — the gate tests get whatever `chat_view` returns today (200 or 429), not 403.

- [ ] **Step 3: Add the gate**

In `src/backend/assistant/views.py`, extend the imports:

```python
from core.privacy import AI_CONSENT_REQUIRED, ahas_ai_consent
```

Then, in `chat_view`, immediately after the authentication check and **before** the `AgentScope` is built:

```python
    user = await aget_user(request)
    if not user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=403)

    # E13 / LGPD art. 7º, I. The ledger runs on execução de contrato and needs
    # no permission; this leg sends what the person wrote to OpenAI, and that
    # is a choice they make. Checked BEFORE `decide` so a refusal opens no
    # interaction and charges no credit — a gate that still billed for saying
    # no would be worse than no gate.
    if not await ahas_ai_consent(user):
        return JsonResponse({"error": AI_CONSENT_REQUIRED}, status=403)
```

- [ ] **Step 4: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_ai_consent_gate.py -q
```

Expected: 8 passed.

- [ ] **Step 5: Run the whole assistant suite, and expect it to go red**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/ -q
```

Expected: **many failures**, all of them 403s from tests that post to `chat_view` with a user who has never consented. This is the gate working. The fix is a fixture, not a weakening of the gate — add to `src/backend/assistant/tests/conftest.py` (create it if absent):

```python
"""Assistant-suite fixtures."""

import pytest


@pytest.fixture
def consented_user(user):
    """A user who has authorised the AI processing (E13).

    Most of this suite is about what the assistant *does*, not about whether it
    is allowed to. Without this, every one of those tests would assert a 403
    from the consent gate and prove nothing about the behaviour it names.

    A test that is actually about the gate asks for `user` and sets consent
    itself — see `test_ai_consent_gate.py`.
    """
    from core.privacy import set_ai_consent

    set_ai_consent(user, granted=True)
    return user
```

…and change each failing test's client fixture so the user has consented. The
smallest correct edit for a test that uses `logged_client` is to also request
`consented_user`:

```python
def test_something_about_the_assistant(logged_client, consented_user):
    ...
```

Work through the list until the suite is green. **Do not** default `Consent.granted` to `True` to make this go away — that would make the consent mechanism decorative, which is precisely what D3a forbids.

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/ -q
```

Expected: all green.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/assistant/
git commit -m "feat(E13): the assistant asks before sending anything to OpenAI"
```

---

## Task 5: The one foreign key that still takes the household's history with it

**Files:**
- Modify: `src/backend/assistant/models.py`
- Create: `src/backend/assistant/migrations/00XX_usage_interaction_user_set_null.py` (generated)
- Modify: `src/backend/accounts/tests/test_tenancy_bases.py`
- Test: `src/backend/assistant/tests/test_usage_survives_a_departure.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `assistant.UsageInteraction.user` becomes `SET_NULL, null=True, blank=True`. Task 6's deletion service depends on this being true; every read of `interaction.user` in the codebase must tolerate `None` after it.

This is D10. Every authored model in this product is `SET_NULL` so that *"deleting a person must never delete the family's financial history"* (`accounts/models.py:157-167`, asserted at `accounts/tests/test_tenancy_bases.py:66-72`). `UsageInteraction.user` is the single exception, and it is not a deliberate one — it means that today, one member deleting their account silently erases the household's record of what its AI usage cost, which is both E07's operator report and what E15 will bill from.

- [ ] **Step 1: Write the failing test**

Create `src/backend/assistant/tests/test_usage_survives_a_departure.py`:

```python
"""What a household spent is the household's record, not the leaver's.

E04 settled this for every other authored table: `created_by` is SET_NULL so
the ledger outlives the person who typed it. `UsageInteraction.user` was the
one column that still cascaded — which meant a member deleting their account
deleted the household's credit history along with themselves, quietly, and
took E07's cost report and E15's future invoice with it.
"""

import pytest
from django.db import models
from model_bakery import baker

from assistant.models import InteractionKind, UsageInteraction, UsageRecord

pytestmark = pytest.mark.django_db


def test_the_column_is_set_null_like_every_other_authored_column():
    field = UsageInteraction._meta.get_field("user")
    assert field.null is True
    assert field.remote_field.on_delete is models.SET_NULL


def test_deleting_a_member_leaves_the_households_interactions_behind(household, user):
    interaction = baker.make(
        UsageInteraction, household=household, user=user, kind=InteractionKind.TEXT
    )

    user.delete()

    interaction.refresh_from_db()
    assert interaction.user is None
    assert interaction.household_id == household.id


def test_deleting_a_member_leaves_the_cost_records_behind(household, user):
    """`UsageRecord.interaction` is SET_NULL, so before this change the records
    survived while their parent vanished — half a history, which is worse than
    either whole answer."""
    interaction = baker.make(
        UsageInteraction, household=household, user=user, kind=InteractionKind.TEXT
    )
    record = baker.make(UsageRecord, household=household, user=user, interaction=interaction)

    user.delete()

    record.refresh_from_db()
    assert record.user is None
    assert record.interaction_id == interaction.id


def test_deleting_the_household_still_takes_all_of_it(household, user):
    """SET_NULL on the person, CASCADE on the tenant. Loosening the first must
    not loosen the second."""
    baker.make(UsageInteraction, household=household, user=user, kind=InteractionKind.TEXT)
    household_id = household.id

    household.delete()

    assert not UsageInteraction.objects.filter(household_id=household_id).exists()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_usage_survives_a_departure.py -q
```

Expected: FAIL — `assert field.null is True` fails, and `test_deleting_a_member_leaves_the_households_interactions_behind` fails with `UsageInteraction matching query does not exist` because the cascade took it.

- [ ] **Step 3: Change the field**

In `src/backend/assistant/models.py`, inside `class UsageInteraction`, replace the `user` field with:

```python
    # SET_NULL, like every other column naming a person in this codebase
    # (`AuthoredHouseholdModel.created_by`). What a household spent is the
    # household's record: it is E07's cost report and E15's invoice, and a
    # member deleting their account must not take it with them. E13 changed
    # this from CASCADE — see docs/superpowers/plans/2026-08-17-E13-lgpd-compliance.md,
    # decision D10.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
```

Confirm `from django.conf import settings` is already imported in that module; it is, because `UsageRecord.user` already uses `settings.AUTH_USER_MODEL`.

- [ ] **Step 4: Generate and inspect the migration**

```bash
uv run python src/backend/manage.py makemigrations assistant \
  -n usage_interaction_user_set_null
```

Open it. It must contain exactly one `AlterField` on `usageinteraction.user`. It is reversible: reversing re-imposes `NOT NULL`, which fails only if a row has already been nulled — that is correct behaviour for a reverse, and worth knowing before running one on production data.

```bash
uv run python src/backend/manage.py migrate assistant
uv run python src/backend/manage.py makemigrations --check --dry-run
```

Expected: `No changes detected`.

- [ ] **Step 5: Update E04's assertion, because this epic deliberately changed it**

In `src/backend/accounts/tests/test_tenancy_bases.py`, the docstring of
`test_registry_holds_exactly_the_seventeen_household_owned_models` explains why
`UsageInteraction` is household-owned. Add one sentence to it:

```python
    E13 changed `UsageInteraction.user` from CASCADE to SET_NULL so this table
    behaves like every other one in this list when a member leaves — see
    `assistant/tests/test_usage_survives_a_departure.py`.
```

No assertion in that file changes; the set of household-owned models is
unaffected.

- [ ] **Step 6: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/tests/test_usage_survives_a_departure.py -q
POSTGRES_PORT=5433 uv run pytest src/backend/assistant/ src/backend/accounts/ src/backend/core/ -q
```

Expected: all green. Anything that read `interaction.user.email` without a
guard will surface here; the fix is a guard, not a revert.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/assistant/ src/backend/accounts/tests/test_tenancy_bases.py
git commit -m "fix(E13): a member leaving no longer erases the household's usage history"
```

---

## Task 6: The deletion service

**Files:**
- Create: `src/backend/core/privacy/deletion.py`
- Modify: `src/backend/core/privacy/__init__.py`
- Test: `src/backend/core/tests/test_privacy_deletion.py`

**Interfaces:**
- Consumes: `core.privacy.INVENTORY`, `Disposal`, `model_for` (Task 1); `UsageInteraction.user` is `SET_NULL` (Task 5).
- Produces:
  - `core.privacy.deletion.DeletionReceipt` — frozen dataclass: `email: str`, `households_deleted: list[str]`, `households_kept: list[str]`, `rows_deleted: dict[str, int]`, `owner_promoted_to: str | None`.
  - `core.privacy.delete_account(user) -> DeletionReceipt`.

Task 8 calls it from a view. Nothing else may.

**This task holds the epic's one exception to global constraint 4** (no `filter(user=...)` on a domain model). Deleting a person's own rows is a per-user query by definition. It lives here, in one function, and the exception is written into the module docstring so a reviewer meets it before the code.

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_privacy_deletion.py`:

```python
"""Nothing personal survives a deletion, and nothing shared is destroyed by one.

Two halves, and they pull against each other on purpose:

  * the parameterized sweep proves no table was forgotten — it walks the
    inventory rather than a list somebody typed here, so a model added next
    year is covered without anyone remembering to cover it;
  * the household cases prove the sweep did not take the other member's
    ledger with it (plan decision D1).
"""

import pytest
from django.contrib.sessions.models import Session
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from accounts.models import Household, Membership, Role
from core.privacy import INVENTORY, Disposal, delete_account, model_for

pytestmark = pytest.mark.django_db


AUTHORED = [record for record in INVENTORY if record.disposal is Disposal.AUTHOR]


@pytest.fixture
def two_person_household(household, user):
    """`user` owns it; `socia` is a plain member. The case D1 is about."""
    socia = baker.make("core.CustomUser", username="socia", email="socia@example.com")
    Membership.objects.create(user=socia, household=household, role=Role.MEMBER)
    return household, user, socia


class TestNothingPersonalSurvives:
    @pytest.mark.parametrize("record", AUTHORED, ids=lambda r: r.label)
    def test_the_rows_this_person_wrote_are_gone(self, record, two_person_household):
        """Parameterized over the inventory, not over a hand-written list. That
        is the whole reason the inventory exists."""
        household, owner, socia = two_person_household
        model = model_for(record)
        row = baker.make(model, household=household, **{record.subject_field: socia})

        delete_account(socia)

        assert not model.objects.filter(pk=row.pk).exists(), (
            f"{record.label} row written by the deleted person survived"
        )

    @pytest.mark.parametrize("record", AUTHORED, ids=lambda r: r.label)
    def test_the_other_members_rows_are_untouched(self, record, two_person_household):
        household, owner, socia = two_person_household
        model = model_for(record)
        theirs = baker.make(model, household=household, **{record.subject_field: owner})

        delete_account(socia)

        assert model.objects.filter(pk=theirs.pk).exists(), (
            f"deleting one person took another person's {record.label} with it"
        )

    def test_the_account_itself_is_gone(self, two_person_household):
        from core.models import CustomUser

        _, _, socia = two_person_household
        delete_account(socia)
        assert not CustomUser.objects.filter(email="socia@example.com").exists()

    def test_the_email_address_and_second_factor_go_with_the_account(
        self, two_person_household
    ):
        from allauth.account.models import EmailAddress
        from allauth.mfa.models import Authenticator

        _, _, socia = two_person_household
        EmailAddress.objects.create(user=socia, email=socia.email, verified=True, primary=True)
        Authenticator.objects.create(user=socia, type=Authenticator.Type.TOTP, data={})

        delete_account(socia)

        assert not EmailAddress.objects.filter(email="socia@example.com").exists()
        assert not Authenticator.objects.exists()

    def test_the_consent_and_acceptance_records_go_too(self, two_person_household):
        """CASCADE by design (Task 2): a statement about a person has no meaning
        once the person is gone."""
        from core.models import Consent, PolicyAcceptance, PolicyDocument
        from core.privacy import set_ai_consent

        _, _, socia = two_person_household
        set_ai_consent(socia, granted=True)
        PolicyAcceptance.objects.create(
            user=socia, document=PolicyDocument.TERMS, version="2026-08-17"
        )

        delete_account(socia)

        assert not Consent.objects.exists()
        assert not PolicyAcceptance.objects.exists()

    def test_their_failed_login_attempts_are_gone(self, two_person_household):
        """`LoginAttempt` has no foreign key — it is keyed by the address
        string — so nothing deletes it unless this service does."""
        from core.models import LoginAttempt

        _, _, socia = two_person_household
        LoginAttempt.objects.create(username="socia@example.com", ip="203.0.113.7")
        LoginAttempt.objects.create(username="alguem@example.com", ip="203.0.113.7")

        delete_account(socia)

        assert not LoginAttempt.objects.filter(username="socia@example.com").exists()
        assert LoginAttempt.objects.filter(username="alguem@example.com").exists()

    def test_their_sessions_are_gone_so_an_open_tab_is_signed_out(
        self, two_person_household
    ):
        """A session outliving its user is not a data leak — `get_user` returns
        AnonymousUser once the row is gone — but leaving it there means the
        person is 'signed in' to nothing, which reads as the deletion having
        failed."""
        _, _, socia = two_person_household
        client = Client()
        client.force_login(socia)
        assert Session.objects.count() == 1

        delete_account(socia)

        assert Session.objects.count() == 0

    def test_a_memory_rules_embedding_goes_with_the_rule(self, two_person_household):
        """`MemoryEmbedding` is household-owned and has no author column, so the
        sweep above cannot reach it. Its id is derived from the rule's, which is
        what makes this reachable at all."""
        from assistant.models import MemoryEmbedding, MemoryRule, MemorySource
        from assistant.tasks import embedding_id_for

        household, _, socia = two_person_household
        rule = MemoryRule.objects.create(
            household=household,
            created_by=socia,
            trigger="cosmos",
            field="category",
            value="Alimentação",
            source=MemorySource.USER_CORRECTION,
        )
        MemoryEmbedding.objects.create(
            id=embedding_id_for(rule.pk),
            household=household,
            text="cosmos → category=Alimentação",
            embedding=[0.0] * 1536,
        )

        delete_account(socia)

        assert not MemoryEmbedding.objects.filter(id=embedding_id_for(rule.pk)).exists()


class TestWhatTheHouseholdKeeps:
    def test_the_ledger_survives_for_whoever_is_left(self, two_person_household):
        from finances.models import Entry

        household, owner, socia = two_person_household
        entry = baker.make(Entry, household=household, created_by=socia)

        delete_account(socia)

        entry.refresh_from_db()
        assert entry.created_by is None
        assert entry.household_id == household.id

    def test_the_household_itself_survives(self, two_person_household):
        household, owner, socia = two_person_household
        delete_account(socia)
        assert Household.objects.filter(pk=household.pk).exists()

    def test_the_remaining_member_can_still_get_in(self, two_person_household):
        household, owner, socia = two_person_household
        delete_account(socia)
        assert Membership.objects.filter(user=owner, household=household).exists()

    def test_the_usage_history_survives_with_the_person_removed_from_it(
        self, two_person_household
    ):
        """Task 5's change, asserted from the deletion side."""
        from assistant.models import InteractionKind, UsageInteraction

        household, owner, socia = two_person_household
        interaction = baker.make(
            UsageInteraction, household=household, user=socia, kind=InteractionKind.TEXT
        )

        delete_account(socia)

        interaction.refresh_from_db()
        assert interaction.user is None


class TestTheLastOwnerLeaving:
    def test_the_longest_standing_member_is_promoted(self, two_person_household):
        """D1, and `accounts/models.py:109` says this is what E13 would do."""
        household, owner, socia = two_person_household

        receipt = delete_account(owner)

        promoted = Membership.objects.get(user=socia, household=household)
        assert promoted.role == Role.OWNER
        assert receipt.owner_promoted_to == "socia@example.com"

    def test_promotion_picks_the_oldest_membership_when_there_are_several(
        self, household, user
    ):
        """Deterministic, because `Membership.Meta.ordering` is `created_at` and
        `membership_household_age_idx` exists for exactly this."""
        first = baker.make("core.CustomUser", username="a", email="primeira@example.com")
        second = baker.make("core.CustomUser", username="b", email="segunda@example.com")
        Membership.objects.create(user=first, household=household, role=Role.MEMBER)
        Membership.objects.create(user=second, household=household, role=Role.MEMBER)

        receipt = delete_account(user)

        assert receipt.owner_promoted_to == "primeira@example.com"
        assert Membership.objects.get(user=first).role == Role.OWNER
        assert Membership.objects.get(user=second).role == Role.MEMBER

    def test_nobody_is_promoted_when_an_owner_remains(self, household, user):
        co_owner = baker.make("core.CustomUser", username="c", email="co@example.com")
        Membership.objects.create(user=co_owner, household=household, role=Role.OWNER)

        receipt = delete_account(user)

        assert receipt.owner_promoted_to is None
        assert Membership.objects.get(user=co_owner).role == Role.OWNER


class TestTheLastMemberLeaving:
    def test_the_household_and_everything_in_it_is_deleted(self, household, user):
        from assistant.models import ChatMessage, MessageRole
        from finances.models import Entry

        entry = baker.make(Entry, household=household, created_by=user)
        baker.make(
            ChatMessage, household=household, created_by=user, role=MessageRole.USER
        )
        household_id = household.id

        receipt = delete_account(user)

        assert not Household.objects.filter(pk=household_id).exists()
        assert not Entry.objects.filter(pk=entry.pk).exists()
        assert not ChatMessage.objects.exists()
        assert receipt.households_deleted == [str(household_id)]
        assert receipt.households_kept == []

    def test_the_uploaded_and_exported_files_go_too(self, household, user, tmp_path):
        """Deleting the database is not deleting the data.

        An uploaded CSV is the household's whole transaction history and an
        export archive is the same thing zipped. Without this they sit in the
        bucket for up to seven more days after the person was told everything
        was gone. The session-scoped `isolated_job_storage` fixture points
        storage at a temp dir, so this exercises the real code path.
        """
        from django.core.files.base import ContentFile

        from core.storage import job_storage
        from finances.models import ExportJob, ExportStatus, ImportJob

        storage = job_storage()
        upload = storage.save("imports/x.csv", ContentFile(b"data,valor\n01/01/2026,10,00\n"))
        archive = storage.save("exports/x.zip", ContentFile(b"PK\x03\x04"))
        baker.make(ImportJob, household=household, created_by=user, storage_key=upload)
        baker.make(
            ExportJob,
            household=household,
            created_by=user,
            status=ExportStatus.DONE,
            storage_key=archive,
        )

        delete_account(user)

        assert not storage.exists(upload)
        assert not storage.exists(archive)

    def test_a_missing_blob_does_not_fail_the_deletion(self, household, user):
        """The transaction has already committed by then. Raising here would
        report a failure for a deletion that actually happened."""
        from finances.models import ImportJob

        baker.make(
            ImportJob, household=household, created_by=user, storage_key="imports/gone.csv"
        )

        receipt = delete_account(user)

        assert receipt.email == "vagner@example.com"

    def test_a_shared_households_files_are_kept(self, two_person_household):
        """The household survives, so its import history and its files do too."""
        from django.core.files.base import ContentFile

        from core.storage import job_storage
        from finances.models import ImportJob

        household, owner, socia = two_person_household
        storage = job_storage()
        key = storage.save("imports/shared.csv", ContentFile(b"x"))
        baker.make(ImportJob, household=household, created_by=socia, storage_key=key)

        delete_account(socia)

        assert storage.exists(key)

    def test_a_neighbouring_households_data_is_untouched(
        self, household, user, other_household, other_user
    ):
        """The whole of E04, restated as a deletion property."""
        from finances.models import Entry

        theirs = baker.make(Entry, household=other_household, created_by=other_user)

        delete_account(user)

        assert Entry.objects.filter(pk=theirs.pk).exists()
        assert Household.objects.filter(pk=other_household.pk).exists()


class TestAPersonInSeveralHouseholds:
    def test_each_household_is_decided_on_its_own(self, household, user):
        """One they share and one they are alone in: the first survives, the
        second does not, in a single call."""
        alone = Household.objects.create(name="Só minha")
        Membership.objects.create(user=user, household=alone, role=Role.OWNER)
        socia = baker.make("core.CustomUser", username="socia", email="socia@example.com")
        Membership.objects.create(user=socia, household=household, role=Role.MEMBER)

        receipt = delete_account(user)

        assert Household.objects.filter(pk=household.pk).exists()
        assert not Household.objects.filter(pk=alone.pk).exists()
        assert receipt.households_kept == [str(household.id)]
        assert receipt.households_deleted == [str(alone.id)]


class TestTheReceipt:
    def test_it_names_the_address_that_was_deleted(self, household, user):
        receipt = delete_account(user)
        assert receipt.email == "vagner@example.com"

    def test_it_counts_what_it_removed(self, two_person_household):
        from assistant.models import ChatMessage, MessageRole

        household, owner, socia = two_person_household
        baker.make(
            ChatMessage,
            household=household,
            created_by=socia,
            role=MessageRole.USER,
            _quantity=3,
        )

        receipt = delete_account(socia)

        assert receipt.rows_deleted["assistant.ChatMessage"] == 3

    def test_it_is_all_or_nothing(self, two_person_household, monkeypatch):
        """One transaction. A deletion that half-happened would leave a person
        who cannot sign in and whose data is still there — the worst of both."""
        from core.models import CustomUser
        from core.privacy import deletion

        household, owner, socia = two_person_household

        def explode(*args, **kwargs):
            raise RuntimeError("the database went away")

        # `_delete_sessions_for` runs INSIDE the atomic block, which is what
        # makes this a rollback test. `_delete_stored_files` deliberately runs
        # outside it and deliberately never raises — see its docstring.
        monkeypatch.setattr(deletion, "_delete_sessions_for", explode)

        with pytest.raises(RuntimeError):
            delete_account(socia)

        assert CustomUser.objects.filter(email="socia@example.com").exists()
        assert Membership.objects.filter(user=socia).exists()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_privacy_deletion.py -q
```

Expected: FAIL — `ImportError: cannot import name 'delete_account' from 'core.privacy'`.

- [ ] **Step 3: Write the deletion service**

Create `src/backend/core/privacy/deletion.py`:

```python
"""Deleting a person without deleting the household they were part of.

Plan decision D1, which is E13's answer to the epic's open question 4 and to
E04's open question 3. In one sentence: *their* data goes, the *household's*
data stays for whoever is still using it, and a household nobody is left in
goes with them.

Almost nothing here is a `.delete()` call, because E04 already did most of the
work: `AuthoredHouseholdModel.created_by` is SET_NULL, so a person vanishing
from the ledger is already the database's default behaviour. What is left is
the part a foreign key cannot express — which rows are *theirs* rather than the
household's, who owns the household once the owner leaves, and the two tables
(`LoginAttempt`, `Session`) that name a person by string rather than by key.

GLOBAL CONSTRAINT 4, AND THE ONE EXCEPTION THIS EPIC TAKES TO IT.
`INDEX.md` §7.4 forbids `filter(user=...)` on a domain model: reads go through
the household-scoped manager, always. This module is the exception, and it has
to be — "delete the rows this person wrote" is a per-person query by
definition, and no household-scoped manager can express it. The exception is
this file and nothing else. It uses `_base_manager` rather than `objects` so
the scoped manager is bypassed deliberately and visibly, instead of being
quietly subverted.
"""

import logging
from dataclasses import dataclass, field

from django.contrib.sessions.models import Session
from django.db import transaction

from accounts.models import Membership, Role
from core.privacy.inventory import INVENTORY, Disposal, model_for

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeletionReceipt:
    """What was actually removed. Shown to the person, and logged.

    A receipt rather than a bare success flag because deletion is irreversible
    and silent success is indistinguishable from silent failure. "3 mensagens,
    1 casa apagada" is a claim someone can check.
    """

    email: str
    households_deleted: list[str] = field(default_factory=list)
    households_kept: list[str] = field(default_factory=list)
    rows_deleted: dict[str, int] = field(default_factory=dict)
    owner_promoted_to: str | None = None


def delete_account(user) -> DeletionReceipt:
    """Remove ``user`` and everything that is theirs. Irreversible.

    One transaction: a deletion that half-happened leaves a person who cannot
    sign in and whose data is still there, which is the worst of both outcomes
    and the hardest to notice.

    The caller is responsible for offering an export first — that gate is a
    product decision and lives in the view (S13-1), not here, so that an
    operator fulfilling a request by hand can call this directly.
    """
    receipt_email = user.email
    households_deleted: list[str] = []
    households_kept: list[str] = []
    rows_deleted: dict[str, int] = {}
    promoted_to: str | None = None
    doomed_files: list[str] = []

    with transaction.atomic():
        memberships = list(
            Membership.objects.filter(user=user).select_related("household")
        )

        for membership in memberships:
            household = membership.household
            others = Membership.objects.filter(household=household).exclude(user=user)

            if not others.exists():
                # Nobody left. The household's CASCADE takes every
                # household-owned row with it — eighteen tables, discovered by
                # `accounts.household_owned_models()` rather than listed.
                #
                # Collected BEFORE the delete, because the rows carrying the
                # storage keys are about to cascade away with it.
                doomed_files.extend(_storage_keys_for(household))
                households_deleted.append(str(household.id))
                household.delete()
                continue

            households_kept.append(str(household.id))
            if membership.role == Role.OWNER and not others.filter(role=Role.OWNER).exists():
                # D1: the longest-standing member takes over. Deterministic
                # because `Membership.Meta.ordering` is `created_at`, and
                # `membership_household_age_idx` exists for this query.
                heir = others.select_related("user").order_by("created_at").first()
                heir.role = Role.OWNER
                heir.save(update_fields=["role"])
                promoted_to = heir.user.email
                logger.info(
                    "Household %s: %s left as sole owner; promoted %s.",
                    household.id,
                    receipt_email,
                    promoted_to,
                )

            _delete_authored_rows(user, household, rows_deleted)

        _delete_login_attempts_for(user, rows_deleted)
        _delete_sessions_for(user, rows_deleted)

        # Last. CASCADE takes Membership, EmailAddress, EmailConfirmation,
        # Authenticator, LogEntry, PolicyAcceptance and Consent; SET_NULL
        # empties every `created_by` and every `user` column we chose to keep.
        user.delete()

    # After the commit, deliberately. Object storage is not transactional: if
    # the blobs went first and the transaction then rolled back, the rows would
    # survive pointing at files that no longer exist. This way the worst case is
    # a file the bucket's own 7-day lifecycle rule collects anyway.
    _delete_stored_files(doomed_files, rows_deleted)

    logger.info(
        "Account deleted: %s, %d household(s) removed, %d kept.",
        receipt_email,
        len(households_deleted),
        len(households_kept),
    )
    return DeletionReceipt(
        email=receipt_email,
        households_deleted=households_deleted,
        households_kept=households_kept,
        rows_deleted=rows_deleted,
        owner_promoted_to=promoted_to,
    )


def _delete_authored_rows(user, household, counts: dict[str, int]) -> None:
    """The rows this person wrote, inside a household that outlives them.

    Driven by the inventory. A model added later with ``Disposal.AUTHOR`` is
    covered here without anyone editing this function, which is the point of
    the registry existing at all.
    """
    for record in INVENTORY:
        if record.disposal is not Disposal.AUTHOR:
            continue
        model = model_for(record)
        rows = model._base_manager.filter(
            household=household, **{record.subject_field: user}
        )
        if record.label == "assistant.MemoryRule":
            _delete_embeddings_for(rows)
        deleted, _ = rows.delete()
        if deleted:
            counts[record.label] = counts.get(record.label, 0) + deleted


def _delete_embeddings_for(rules) -> None:
    """A memory rule's vector, which no foreign key points at.

    `MemoryEmbedding` is household-owned and carries no author column; its
    primary key is `uuid5(namespace, rule_id)` (`assistant/tasks.py:24-32`),
    which is the only handle there is. Missing this would leave a vector of
    someone's shopping habits in the database after they had been told it was
    gone.
    """
    from assistant.models import MemoryEmbedding
    from assistant.tasks import embedding_id_for

    ids = [embedding_id_for(pk) for pk in rules.values_list("pk", flat=True)]
    if ids:
        MemoryEmbedding._base_manager.filter(id__in=ids).delete()


def _storage_keys_for(household) -> list[str]:
    """Every blob this household owns, before its rows cascade away.

    Deleting the database is not deleting the data. The uploaded CSV is a
    household's whole transaction history and the export archive is the same
    thing zipped; both sit in object storage under keys that only these rows
    know. Without this, "your data is deleted" would be true of Postgres and
    false of the bucket for up to seven more days.
    """
    from finances.models import ExportJob, ImportJob

    keys = list(
        ImportJob._base_manager.filter(household=household)
        .exclude(storage_key="")
        .values_list("storage_key", flat=True)
    )
    keys += list(
        ExportJob._base_manager.filter(household=household)
        .exclude(storage_key="")
        .values_list("storage_key", flat=True)
    )
    return keys


def _delete_stored_files(keys: list[str], counts: dict[str, int]) -> None:
    """Remove the blobs, tolerating every way that can fail.

    Never raises. By the time this runs the database transaction has committed,
    so an exception here would report a failure for a deletion that already
    happened — and the bucket's 7-day lifecycle rule (E12 decision 2) collects
    anything missed. Belt and braces, in that order.
    """
    if not keys:
        return

    from core.storage import job_storage

    storage = job_storage()
    removed = 0
    for key in keys:
        try:
            storage.delete(key)
            removed += 1
        except Exception:
            logger.warning("Could not delete %s during account deletion.", key, exc_info=True)
    if removed:
        counts["storage.blobs"] = removed


def _delete_login_attempts_for(user, counts: dict[str, int]) -> None:
    """Keyed by the address string, not by a foreign key — so nothing else
    would ever remove these."""
    from core.models import LoginAttempt

    deleted, _ = LoginAttempt.objects.filter(
        username__in={user.email, user.get_username()}
    ).delete()
    if deleted:
        counts["core.LoginAttempt"] = deleted


def _delete_sessions_for(user, counts: dict[str, int]) -> None:
    """Every open session belonging to this person.

    Sessions hold `_auth_user_id` inside encoded data with no column to filter
    on, so they have to be decoded. That is affordable exactly here: this runs
    once per deletion, never per request, and the table is small because
    expired rows are swept daily by the purge job.

    Leaving them would not leak anything — `get_user` returns AnonymousUser
    once the row behind the id is gone — but it would leave the person's other
    tab believing it is signed in, which reads as the deletion not having
    worked.
    """
    target = str(user.pk)
    doomed = [
        session.session_key
        for session in Session.objects.iterator()
        if session.get_decoded().get("_auth_user_id") == target
    ]
    if doomed:
        deleted, _ = Session.objects.filter(session_key__in=doomed).delete()
        counts["sessions.Session"] = deleted
```

- [ ] **Step 4: Export it**

In `src/backend/core/privacy/__init__.py`, add to the imports and to `__all__`:

```python
from core.privacy.deletion import DeletionReceipt, delete_account
```

```python
    "DeletionReceipt",
    "delete_account",
```

- [ ] **Step 5: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_privacy_deletion.py -q
```

Expected: all passed. The parameterized sweep runs once per `Disposal.AUTHOR` record — four today (`assistant.ChatMessage`, `assistant.MemoryRule`, `assistant.ReceiptDraft`, `core.Feedback`) — so 8 parameterized cases plus the rest.

If `baker.make(model, ...)` fails for one of them because the model needs a
required related object, give that record its own explicit test beside the
sweep rather than weakening the sweep. The sweep's value is that it is
automatic; an exception written down beside it is honest, a `try/except`
inside it is not.

- [ ] **Step 6: Prove the test can actually fail**

Delete one line from `_delete_authored_rows` — the `deleted, _ = rows.delete()` —
and re-run. `test_the_rows_this_person_wrote_are_gone` must go red for all four
parameterizations. Put the line back.

This step is not optional. A "no personal data survives deletion" test that
passes whether or not the deletion happens is the single most dangerous
artifact this epic could produce, and this repo has been bitten by exactly that
before (`docs/superpowers/plans/` — E12's H5).

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/core/privacy/ src/backend/core/tests/test_privacy_deletion.py
git commit -m "feat(E13): delete an account without deleting the household"
```

---

## Task 7: The Privacidade tab

**Files:**
- Modify: `src/backend/accounts/views_account.py`
- Modify: `src/backend/accounts/urls.py`
- Modify: `src/backend/templates/accounts/account_page.html`
- Create: `src/backend/templates/accounts/_privacy_tab.html`
- Test: `src/backend/accounts/tests/test_privacy_tab.py`

**Interfaces:**
- Consumes: `_TabView` (`accounts/views_account.py:31`); `core.privacy.has_ai_consent`, `set_ai_consent` (Task 2); `core.privacy.record_for` (Task 1).
- Produces:
  - URL name `account_privacy_tab` → `/casa/conta/privacidade/`.
  - URL name `account_ai_consent` → `/casa/conta/privacidade/ia/` (POST only).
  - URL name `account_memory_rule_delete` → `/casa/conta/privacidade/memoria/<uuid:pk>/apagar/` (POST only).
  - Context keys `ai_consent`, `memory_rules`, `acceptances`, `chat_retention_days`, `draft_retention_days`.

This tab is S13-2. It is where a person exercises access, correction and portability without writing to support — and where they see the thing the epic says they are most likely to find surprising: the rules the assistant has inferred about them. Deletion is Task 8 and appears here as one link.

- [ ] **Step 1: Run the daisyUI Blueprint chain, steps 1–4**

`workflowId: e13-privacidade`, `projectRoot: /home/bessa/Documents/projetos/expense_tracker_v2`, `install: false`. Setup Expert → Rules Enforcer → Component Syntax Expert for: `card`, `list`, `badge`, `btn`, `toggle`, `alert`, `link`, `table`. Skip Creative Director and Page Architect.

- [ ] **Step 2: Write the failing test**

Create `src/backend/accounts/tests/test_privacy_tab.py`:

```python
"""Privacidade: see it, correct it, take it with you.

S13-2. The access right is not "we would send it if you emailed us" — it is a
page. The correction right is not "we would change it" — it is a button. This
suite is what makes those two sentences true.
"""

import pytest
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from assistant.models import MemoryRule, MemorySource
from core.privacy import has_ai_consent, set_ai_consent

pytestmark = pytest.mark.django_db


@pytest.fixture
def rule(household, user):
    return MemoryRule.objects.create(
        household=household,
        created_by=user,
        trigger="cosmos",
        field="category",
        value="Alimentação",
        source=MemorySource.INFERRED,
    )


class TestTheTab:
    def test_it_requires_login(self):
        response = Client().get(reverse("account_privacy_tab"))
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    def test_the_fragment_url_renders_standalone(self, logged_client, household):
        response = logged_client.get(reverse("account_privacy_tab"))
        assert response.status_code == 200
        assert "<!DOCTYPE html>" in response.content.decode()

    def test_as_an_htmx_fragment_it_is_not_a_whole_page(self, logged_client, household):
        response = logged_client.get(
            reverse("account_privacy_tab"), headers={"HX-Request": "true"}
        )
        assert "<!DOCTYPE html>" not in response.content.decode()

    def test_the_conta_page_offers_it_as_a_tab(self, logged_client, household):
        body = logged_client.get(reverse("account")).content.decode()
        assert reverse("account_privacy_tab") in body
        assert "Privacidade" in body


class TestPortability:
    def test_it_sends_you_to_the_export_rather_than_reinventing_one(
        self, logged_client, household
    ):
        """E12 already built this. E13 consumes it — the epic says so in as
        many words, and a second export path is a second thing to keep correct."""
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert reverse("finances:export_page") in body


class TestWhatTheAssistantThinksItKnows:
    def test_the_inferred_rules_are_shown(self, logged_client, household, rule):
        """The epic's own words: users have a right to see these and are likely
        to find them surprising."""
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert "cosmos" in body
        assert "Alimentação" in body

    def test_a_neighbours_rules_are_not_shown(
        self, logged_client, household, other_household, other_user
    ):
        MemoryRule.objects.create(
            household=other_household,
            created_by=other_user,
            trigger="segredo-da-vizinha",
            field="category",
            value="Outros",
            source=MemorySource.INFERRED,
        )
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert "segredo-da-vizinha" not in body

    def test_a_rule_can_be_deleted_which_is_the_correction_right(
        self, logged_client, household, rule
    ):
        response = logged_client.post(
            reverse("account_memory_rule_delete", args=[rule.pk]),
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert not MemoryRule.objects.filter(pk=rule.pk).exists()

    def test_deleting_a_rule_takes_its_embedding_with_it(
        self, logged_client, household, rule
    ):
        """Otherwise the vector of that inference survives the correction, and
        semantic lookup keeps finding a rule the person deleted."""
        from assistant.models import MemoryEmbedding
        from assistant.tasks import embedding_id_for

        MemoryEmbedding.objects.create(
            id=embedding_id_for(rule.pk),
            household=household,
            text="cosmos → category=Alimentação",
            embedding=[0.0] * 1536,
        )

        logged_client.post(
            reverse("account_memory_rule_delete", args=[rule.pk]),
            headers={"HX-Request": "true"},
        )

        assert not MemoryEmbedding.objects.filter(id=embedding_id_for(rule.pk)).exists()

    def test_a_neighbours_rule_cannot_be_deleted(
        self, logged_client, household, other_household, other_user
    ):
        """404, not 403: whether a row exists in another household is itself
        something this endpoint must not disclose."""
        theirs = MemoryRule.objects.create(
            household=other_household,
            created_by=other_user,
            trigger="cosmos",
            field="category",
            value="Outros",
            source=MemorySource.INFERRED,
        )
        response = logged_client.post(
            reverse("account_memory_rule_delete", args=[theirs.pk]),
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 404
        assert MemoryRule.objects.filter(pk=theirs.pk).exists()

    def test_a_get_cannot_delete_a_rule(self, logged_client, household, rule):
        """A GET that destroys something is a URL an email scanner follows."""
        response = logged_client.get(reverse("account_memory_rule_delete", args=[rule.pk]))
        assert response.status_code == 405
        assert MemoryRule.objects.filter(pk=rule.pk).exists()


class TestTheConsentToggle:
    def test_it_shows_consent_as_absent_for_a_new_account(self, logged_client, household):
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert "Não autorizado" in body

    def test_granting_it_from_here_works(self, logged_client, household, user):
        response = logged_client.post(
            reverse("account_ai_consent"),
            {"granted": "1"},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert has_ai_consent(user) is True
        assert "Autorizado" in response.content.decode()

    def test_revoking_it_from_here_works(self, logged_client, household, user):
        set_ai_consent(user, granted=True)
        response = logged_client.post(
            reverse("account_ai_consent"),
            {"granted": "0"},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert has_ai_consent(user) is False

    def test_it_cannot_be_used_to_consent_on_somebody_elses_behalf(
        self, logged_client, household, other_user
    ):
        """The view reads `request.user` and takes no id. This asserts that
        stays true if anyone ever adds one."""
        logged_client.post(
            reverse("account_ai_consent"),
            {"granted": "1", "user": other_user.pk, "id": other_user.pk},
            headers={"HX-Request": "true"},
        )
        assert has_ai_consent(other_user) is False


class TestWhatItTellsYou:
    def test_it_states_the_chat_retention_period(self, logged_client, household):
        """Rendered from the inventory, so it cannot drift from what the purge
        job actually does."""
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert "90" in body

    def test_it_links_the_notice_and_the_terms(self, logged_client, household):
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert reverse("privacy_notice") in body
        assert reverse("terms_of_service") in body

    def test_it_shows_which_version_you_accepted(self, logged_client, household, user):
        from core.models import PolicyAcceptance, PolicyDocument

        PolicyAcceptance.objects.create(
            user=user, document=PolicyDocument.PRIVACY, version="2026-08-17"
        )
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert "2026-08-17" in body

    def test_it_offers_the_way_out(self, logged_client, household):
        body = logged_client.get(reverse("account_privacy_tab")).content.decode()
        assert reverse("account_delete") in body
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_privacy_tab.py -q
```

Expected: FAIL — `NoReverseMatch: Reverse for 'account_privacy_tab' not found`.

- [ ] **Step 4: Add the views**

Append to `src/backend/accounts/views_account.py`:

```python
class PrivacyTabView(_TabView):
    """Everything this product knows about you, and the three buttons that
    matter: take a copy, correct it, delete it.

    Reads the inventory for the retention numbers rather than repeating them
    here. A number typed into a template is a number that drifts away from the
    job that enforces it, and this whole epic is about those two agreeing.
    """

    fragment_template_name = "accounts/_privacy_tab.html"
    tab_title = "Privacidade"

    def get_context_data(self, **kwargs):
        from assistant.models import MemoryRule
        from core.models import PolicyAcceptance
        from core.privacy import has_ai_consent, record_for

        context = super().get_context_data(**kwargs)
        context["ai_consent"] = has_ai_consent(self.request.user)
        context["memory_rules"] = MemoryRule.objects.for_request(self.request).order_by(
            "-last_used_at"
        )[:100]
        context["acceptances"] = PolicyAcceptance.objects.filter(user=self.request.user)
        context["chat_retention_days"] = record_for("assistant.ChatMessage").retention_days
        context["draft_retention_days"] = record_for("assistant.ReceiptDraft").retention_days
        return context


class AIConsentView(LoginRequiredMixin, View):
    """Grant or withdraw permission for the AI leg, and re-render the tab.

    POST only, and it names no user: the only consent this can ever write is
    the caller's own.
    """

    def post(self, request, *args, **kwargs):
        from core.privacy import set_ai_consent

        set_ai_consent(request.user, granted=request.POST.get("granted") == "1")
        return _render_privacy_fragment(request)


class MemoryRuleDeleteView(LoginRequiredMixin, View):
    """Forget one thing the assistant concluded about you.

    This is the correction right (S13-2) in its most concrete form. It deletes
    the rule's embedding too — leaving the vector behind would mean semantic
    lookup keeps finding an inference the person just told us to forget.

    404 rather than 403 for a rule in another household: whether a row exists
    over there is itself not ours to disclose.
    """

    def post(self, request, pk, *args, **kwargs):
        from assistant.models import MemoryEmbedding, MemoryRule
        from assistant.tasks import embedding_id_for

        rule = MemoryRule.objects.for_request(request).filter(pk=pk).first()
        if rule is None:
            raise Http404("regra não encontrada")

        MemoryEmbedding.objects.filter(id=embedding_id_for(rule.pk)).delete()
        rule.delete()
        return _render_privacy_fragment(
            request, toast="Regra apagada. O assistente esqueceu isso."
        )


def _render_privacy_fragment(request, toast: str | None = None) -> HttpResponse:
    """Re-render the tab after a write, the way `ProfileTabView.post` does.

    A shared helper rather than a mixin: two small views and one template name,
    and a class hierarchy would be more machinery than the thing it organises.
    """
    view = PrivacyTabView()
    view.setup(request)
    html = render_to_string(
        PrivacyTabView.fragment_template_name,
        view.get_context_data(),
        request=request,
    )
    response = HttpResponse(html)
    if toast:
        response["HX-Trigger"] = json.dumps({"showToast": {"message": toast, "type": "success"}})
    return response
```

Extend that module's imports:

```python
from django.http import Http404, HttpResponse
from django.views import View
```

- [ ] **Step 5: Write the fragment**

Create `src/backend/templates/accounts/_privacy_tab.html`:

```html
{% comment %}
Privacidade. Four things, in the order a worried person asks for them: take a
copy, see what the assistant concluded about you, decide whether it may keep
doing that, and leave.

Every number on this page comes from `core.privacy.INVENTORY` through the view.
Typing "90 dias" here would be one edit away from the purge job disagreeing
with it, and this epic exists because that kind of drift is the violation.
{% endcomment %}
<div class="space-y-6" id="privacy-tab">
    <section class="card bg-base-100 shadow-sm">
        <div class="card-body">
            <h2 class="card-title text-lg">Uma cópia dos seus dados</h2>
            <p class="text-sm opacity-70">
                Um arquivo .zip com tudo: lançamentos, receitas, categorias, orçamentos,
                o histórico de conversas com o assistente e as regras de memória. As
                planilhas saem no mesmo formato que o próprio Ledger importa, então dá
                para levar embora e trazer de volta.
            </p>
            <div class="card-actions mt-4">
                <a href="{% url 'finances:export_page' %}" class="btn btn-accent btn-sm">
                    Baixar meus dados
                </a>
            </div>
        </div>
    </section>

    <section class="card bg-base-100 shadow-sm">
        <div class="card-body">
            <h2 class="card-title text-lg">O que o assistente aprendeu sobre você</h2>
            <p class="text-sm opacity-70">
                Conclusões que ele tirou das suas correções e dos seus cupons. Apagar
                uma faz ele esquecer — e ele pode reaprender depois, se você corrigir
                a mesma coisa de novo.
            </p>
            {% if memory_rules %}
            <ul class="list mt-2">
                {% for rule in memory_rules %}
                <li class="list-row">
                    <div class="list-col-grow break-words">
                        <span class="font-mono text-sm">{{ rule.trigger }}</span>
                        <span class="opacity-50 mx-1">→</span>
                        <span class="text-sm">{{ rule.value }}</span>
                        {% if rule.source == 'inferred' %}
                        <span class="badge badge-ghost badge-xs ml-2">deduzido</span>
                        {% else %}
                        <span class="badge badge-ghost badge-xs ml-2">você corrigiu</span>
                        {% endif %}
                    </div>
                    {# A form, never a link: a GET that deletes is a URL a scanner follows. #}
                    <form hx-post="{% url 'account_memory_rule_delete' rule.pk %}"
                          hx-target="#privacy-tab"
                          hx-swap="outerHTML">
                        {% csrf_token %}
                        <button type="submit" class="btn btn-xs btn-ghost text-error">Apagar</button>
                    </form>
                </li>
                {% endfor %}
            </ul>
            {% else %}
            <p class="text-sm opacity-60 mt-2">
                Nada por enquanto. Ele só guarda alguma coisa depois que você corrige
                uma categoria.
            </p>
            {% endif %}
        </div>
    </section>

    <section class="card bg-base-100 shadow-sm">
        <div class="card-body">
            <div class="flex items-center gap-2 flex-wrap">
                <h2 class="card-title text-lg">Assistente de IA</h2>
                {% if ai_consent %}
                <span class="badge badge-success badge-sm">Autorizado</span>
                {% else %}
                <span class="badge badge-ghost badge-sm">Não autorizado</span>
                {% endif %}
            </div>
            <p class="text-sm opacity-70">
                O assistente envia o que você escreve, fala e fotografa para a
                <strong>OpenAI</strong>, que processa e devolve a resposta. Fotos e
                áudios são processados e descartados na hora — nunca ficam guardados.
                As conversas ficam {{ chat_retention_days }} dias e os rascunhos de
                cupom {{ draft_retention_days }} dias.
            </p>
            <p class="text-sm opacity-70">
                Isso é uma escolha sua, e você pode voltar atrás quando quiser. O
                resto do aplicativo — lançamentos, orçamentos, projeção — funciona
                igual sem isso.
            </p>
            <form hx-post="{% url 'account_ai_consent' %}"
                  hx-target="#privacy-tab"
                  hx-swap="outerHTML"
                  class="card-actions mt-4">
                {% csrf_token %}
                {% if ai_consent %}
                <input type="hidden" name="granted" value="0">
                <button type="submit" class="btn btn-outline btn-sm" data-pending="Salvando…">
                    Retirar autorização
                </button>
                {% else %}
                <input type="hidden" name="granted" value="1">
                <button type="submit" class="btn btn-accent btn-sm" data-pending="Salvando…">
                    Autorizar
                </button>
                {% endif %}
            </form>
        </div>
    </section>

    <section class="card bg-base-100 shadow-sm">
        <div class="card-body">
            <h2 class="card-title text-lg">Documentos</h2>
            <div class="flex gap-2 flex-wrap mt-1">
                <a href="{% url 'privacy_notice' %}" class="btn btn-outline btn-sm">
                    Aviso de Privacidade
                </a>
                <a href="{% url 'terms_of_service' %}" class="btn btn-outline btn-sm">
                    Termos de Uso
                </a>
            </div>
            {% if acceptances %}
            <ul class="text-sm opacity-70 mt-3 space-y-1">
                {% for acceptance in acceptances %}
                <li>
                    {{ acceptance.get_document_display }}, versão
                    <span class="font-mono">{{ acceptance.version }}</span>,
                    aceito em {{ acceptance.accepted_at|date:"d/m/Y" }}.
                </li>
                {% endfor %}
            </ul>
            {% endif %}
        </div>
    </section>

    <section class="card bg-base-100 shadow-sm border border-error/30">
        <div class="card-body">
            <h2 class="card-title text-lg">Excluir minha conta</h2>
            <p class="text-sm opacity-70">
                Apaga sua conta e tudo que é seu. Não dá para desfazer, e o seu
                histórico financeiro não é recuperável depois — então baixe uma cópia
                antes.
            </p>
            <div class="card-actions mt-4">
                <a href="{% url 'account_delete' %}" class="btn btn-outline btn-error btn-sm">
                    Excluir minha conta
                </a>
            </div>
        </div>
    </section>
</div>
```

- [ ] **Step 6: Register the URLs**

In `src/backend/accounts/urls.py`, extend the `views_account` import and add three routes after the Membros one:

```python
from accounts.views_account import (
    AccountView,
    AIConsentView,
    MembersTabView,
    MemoryRuleDeleteView,
    PrivacyTabView,
    ProfileTabView,
    SecurityTabView,
)
```

```python
    path("conta/privacidade/", PrivacyTabView.as_view(), name="account_privacy_tab"),
    path("conta/privacidade/ia/", AIConsentView.as_view(), name="account_ai_consent"),
    path(
        "conta/privacidade/memoria/<uuid:pk>/apagar/",
        MemoryRuleDeleteView.as_view(),
        name="account_memory_rule_delete",
    ),
```

- [ ] **Step 7: Add the tab button**

In `src/backend/templates/accounts/account_page.html`, after the Membros button (line 46) and before the closing `</div>`:

```html
    <button type="button" role="tab" class="tab" id="tab-privacidade" aria-selected="false"
            hx-get="{% url 'account_privacy_tab' %}"
            hx-target="#account-content"
            hx-swap="innerHTML"
            @click="document.querySelectorAll('.tabs .tab').forEach(t => { t.classList.remove('tab-active'); t.setAttribute('aria-selected', 'false'); }); $el.classList.add('tab-active'); $el.setAttribute('aria-selected', 'true')">Privacidade</button>
```

- [ ] **Step 8: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_privacy_tab.py -q
```

Expected: all passed except `test_it_offers_the_way_out`, which reverses `account_delete` — Task 8's URL. If you are executing in order, add the route stub from Task 8 Step 6 now and finish it there.

- [ ] **Step 9: Run the Quality Inspector**

`daisyui_quality_inspector`, `workflowId: e13-privacidade`, `auditIntent: "fix_changes"`, files `src/backend/templates/accounts/_privacy_tab.html` and `src/backend/templates/accounts/account_page.html`, line ranges from `git diff --unified=0`. **Do not change `btn-accent`** — recorded deviation.

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/accounts/ src/backend/templates/accounts/
git commit -m "feat(E13): the Privacidade tab — see it, correct it, take it with you"
```

---

## Task 8: Deleting an account, with the export offered first

**Files:**
- Modify: `src/backend/accounts/views_account.py`
- Modify: `src/backend/accounts/urls.py`
- Create: `src/backend/templates/accounts/_privacy_delete.html`
- Create: `src/backend/templates/accounts/account_deleted.html`
- Test: `src/backend/accounts/tests/test_account_deletion_flow.py`

**Interfaces:**
- Consumes: `core.privacy.delete_account`, `DeletionReceipt` (Task 6).
- Produces: URL name `account_delete` → `/casa/conta/privacidade/excluir/`, GET renders the confirmation, POST performs it and redirects to `account_deleted`. URL name `account_deleted` → `/casa/conta/excluida/`.

Three gates, and each of them earns its place:

1. **The export is offered first**, because S13-1 says so and because a financial history is not recoverable. If the household has no completed export, the page leads with the offer rather than the button.
2. **The exact email address must be typed.** Not a checkbox: a checkbox is one mis-tap, and this is irreversible.
3. **POST only, CSRF-protected, and it names no user** — the only account it can delete is the caller's.

- [ ] **Step 1: Run the daisyUI Blueprint chain, steps 1–4**

`workflowId: e13-exclusao`. Component Syntax Expert for: `card`, `alert`, `fieldset`, `label`, `input`, `btn`, `list`.

- [ ] **Step 2: Write the failing test**

Create `src/backend/accounts/tests/test_account_deletion_flow.py`:

```python
"""Deleting an account from the UI, the way a person actually does it.

The service is tested in `core/tests/test_privacy_deletion.py`. What is tested
here is the path to it: that an export is offered before an irreversible act,
that a mis-tap cannot trigger it, and that nobody can trigger it for somebody
else.
"""

import pytest
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from accounts.models import Membership, Role
from core.models import CustomUser
from finances.models import ExportJob, ExportStatus

pytestmark = pytest.mark.django_db


class TestTheConfirmationPage:
    def test_it_requires_login(self):
        response = Client().get(reverse("account_delete"))
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    def test_it_offers_an_export_when_there_is_none(self, logged_client, household):
        """S13-1: 'they are offered an export first, because deletion is
        irreversible and their financial history is not recoverable'."""
        body = logged_client.get(reverse("account_delete")).content.decode()
        assert reverse("finances:export_page") in body
        assert "Baixar" in body

    def test_it_says_when_the_last_export_was_made(self, logged_client, household, user):
        baker.make(
            ExportJob,
            household=household,
            created_by=user,
            status=ExportStatus.DONE,
            storage_key="exports/x.zip",
        )
        body = logged_client.get(reverse("account_delete")).content.decode()
        assert "Você já baixou" in body

    def test_it_tells_a_lone_member_the_household_goes_too(self, logged_client, household):
        body = logged_client.get(reverse("account_delete")).content.decode()
        assert "toda a casa" in body

    def test_it_tells_a_shared_household_what_the_other_person_keeps(
        self, logged_client, household
    ):
        socia = baker.make("core.CustomUser", username="socia", email="socia@example.com")
        Membership.objects.create(user=socia, household=household, role=Role.MEMBER)
        body = logged_client.get(reverse("account_delete")).content.decode()
        assert "socia@example.com" in body
        assert "continua" in body


class TestTheConfirmation:
    def test_the_wrong_address_deletes_nothing(self, logged_client, household, user):
        response = logged_client.post(
            reverse("account_delete"), {"confirm_email": "outra@example.com"}
        )
        assert response.status_code == 200
        assert CustomUser.objects.filter(pk=user.pk).exists()

    def test_an_empty_confirmation_deletes_nothing(self, logged_client, household, user):
        logged_client.post(reverse("account_delete"), {})
        assert CustomUser.objects.filter(pk=user.pk).exists()

    def test_the_address_match_ignores_case_and_whitespace(
        self, logged_client, household, user
    ):
        """A person copying their own address out of the page should not be
        defeated by a trailing space."""
        logged_client.post(
            reverse("account_delete"), {"confirm_email": "  VAGNER@example.com "}
        )
        assert not CustomUser.objects.filter(pk=user.pk).exists()

    def test_a_get_never_deletes(self, logged_client, household, user):
        logged_client.get(reverse("account_delete"))
        assert CustomUser.objects.filter(pk=user.pk).exists()

    def test_the_right_address_deletes_the_account(self, logged_client, household, user):
        response = logged_client.post(
            reverse("account_delete"), {"confirm_email": "vagner@example.com"}
        )
        assert response.status_code == 302
        assert response["Location"] == reverse("account_deleted")
        assert not CustomUser.objects.filter(pk=user.pk).exists()

    def test_it_signs_you_out(self, logged_client, household, user):
        logged_client.post(reverse("account_delete"), {"confirm_email": user.email})
        response = logged_client.get(reverse("account"))
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    def test_it_cannot_be_pointed_at_somebody_else(
        self, logged_client, household, other_user
    ):
        """The view reads `request.user` and the form carries no id. This is the
        assertion that stays true if anyone ever adds one."""
        logged_client.post(
            reverse("account_delete"),
            {
                "confirm_email": other_user.email,
                "user": other_user.pk,
                "id": other_user.pk,
            },
        )
        assert CustomUser.objects.filter(pk=other_user.pk).exists()

    def test_it_requires_csrf(self, user, household):
        """Deleting an account on a forged cross-site POST is the worst possible
        CSRF outcome, so this is asserted rather than assumed from middleware."""
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        response = client.post(
            reverse("account_delete"), {"confirm_email": user.email}
        )
        assert response.status_code == 403
        assert CustomUser.objects.filter(pk=user.pk).exists()


class TestTheGoodbyePage:
    def test_it_renders_to_somebody_who_is_not_signed_in(self):
        """It has to: by the time anyone reaches it their account is gone."""
        response = Client().get(reverse("account_deleted"))
        assert response.status_code == 200
        assert "excluída" in response.content.decode()

    def test_it_does_not_redirect_to_login(self):
        assert Client().get(reverse("account_deleted")).status_code == 200
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_account_deletion_flow.py -q
```

Expected: FAIL — `NoReverseMatch: Reverse for 'account_delete' not found`.

- [ ] **Step 4: Add the views**

Append to `src/backend/accounts/views_account.py`:

```python
class AccountDeleteView(LoginRequiredMixin, View):
    """The last screen before an irreversible act.

    GET explains what will happen — which is different depending on whether
    anyone else is in the household — and offers an export if none has been
    taken. POST does it, once the person has typed their own address.

    Typed address rather than a checkbox: a checkbox is one mis-tap, and this
    deletes a financial history that cannot be reconstructed. Same reason the
    export offer is on this page rather than in a help article.
    """

    template_name = "accounts/tab_page.html"
    fragment_template_name = "accounts/_privacy_delete.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._context(request))

    def post(self, request, *args, **kwargs):
        from django.contrib.auth import logout

        typed = (request.POST.get("confirm_email") or "").strip().lower()
        if typed != request.user.email.strip().lower():
            context = self._context(request)
            context["error"] = (
                "Digite exatamente o e-mail da sua conta para confirmar a exclusão."
            )
            return render(request, self.template_name, context)

        receipt = delete_account(request.user)
        # After `delete_account` the session row is already gone, so this is
        # about the request's own state rather than about the store.
        logout(request)
        logger.info("Account deletion completed from the UI: %s", receipt.email)
        return redirect("account_deleted")

    def _context(self, request):
        from finances.models import ExportJob, ExportStatus

        household = request.household
        others = (
            Membership.objects.filter(household=household)
            .exclude(user=request.user)
            .select_related("user")
            if household is not None
            else Membership.objects.none()
        )
        last_export = (
            ExportJob.objects.for_request(request)
            .filter(status=ExportStatus.DONE)
            .order_by("-created_at")
            .first()
        )
        return {
            "fragment_template": self.fragment_template_name,
            "tab_title": "Excluir conta",
            "others": others,
            "household": household,
            "last_export": last_export,
        }


class AccountDeletedView(TemplateView):
    """Deliberately not `LoginRequiredMixin`.

    Everyone who reaches this page has no account, so requiring one would
    redirect them to a login screen for credentials that no longer exist — and
    the last thing they would see is a failure.
    """

    template_name = "accounts/account_deleted.html"
```

Extend that module's imports:

```python
import logging

from django.shortcuts import redirect, render

from core.privacy import delete_account

logger = logging.getLogger(__name__)
```

- [ ] **Step 5: Write the confirmation fragment**

Create `src/backend/templates/accounts/_privacy_delete.html`:

```html
{% comment %}
The last screen before an irreversible act. It says what will actually happen
in this particular household rather than a generic warning, because "sua casa
inteira some" and "a Amanda continua vendo o extrato" are very different facts
and the person deserves the one that is true for them.
{% endcomment %}
<div class="space-y-6">
    <a href="{% url 'account_privacy_tab' %}" class="link link-hover text-sm">← Privacidade</a>

    {% if error %}
    <div role="alert" class="alert alert-error"><span>{{ error }}</span></div>
    {% endif %}

    <section class="card bg-base-100 shadow-sm">
        <div class="card-body">
            <h1 class="card-title text-xl">Baixe uma cópia antes</h1>
            {% if last_export %}
            <p class="text-sm opacity-70">
                Você já baixou uma cópia em {{ last_export.created_at|date:"d/m/Y" }}.
                O arquivo em si fica disponível por 7 dias, então vale conferir se
                você ainda o tem.
            </p>
            {% else %}
            <p class="text-sm opacity-70">
                Você nunca baixou seus dados. Depois da exclusão não há como
                recuperá-los — nem por nós.
            </p>
            {% endif %}
            <div class="card-actions mt-4">
                <a href="{% url 'finances:export_page' %}" class="btn btn-accent btn-sm">
                    Baixar meus dados
                </a>
            </div>
        </div>
    </section>

    <section class="card bg-base-100 shadow-sm border border-error/40">
        <div class="card-body">
            <h2 class="card-title text-lg text-error">O que vai acontecer</h2>
            {% if others %}
            <p class="text-sm opacity-80">
                A casa <strong>{{ household.name }}</strong> continua existindo, porque
                {% for membership in others %}<strong>{{ membership.user.email }}</strong>{% if not forloop.last %}, {% endif %}{% endfor %}
                ainda usa{{ others|length|pluralize:"m" }} ela. O extrato, os orçamentos
                e o histórico da casa continuam lá — sem o seu nome em nada.
            </p>
            <ul class="list-disc list-inside text-sm opacity-80 space-y-1 mt-2">
                <li>Sua conta, sua senha e sua verificação em duas etapas são apagadas.</li>
                <li>Suas conversas com o assistente e as regras que ele aprendeu com
                    você são apagadas.</li>
                <li>Os lançamentos que você cadastrou continuam na casa, sem autor.</li>
                <li>Se você era o único dono, a pessoa que está há mais tempo na casa
                    passa a ser dona.</li>
            </ul>
            {% else %}
            <p class="text-sm opacity-80">
                Você é a única pessoa aqui, então <strong>toda a casa</strong> vai junto:
                lançamentos, receitas, categorias, orçamentos, parcelamentos, conversas
                com o assistente. Tudo.
            </p>
            {% endif %}
            <p class="text-sm opacity-80 mt-2">
                Alguns registros ficam, e o
                <a href="{% url 'privacy_notice' %}" class="link">Aviso de Privacidade</a>
                explica quais e por quê — em resumo: quanto o uso de IA custou, sem o
                seu nome, para responder a uma cobrança ou a uma investigação de abuso.
            </p>

            <form method="post" action="{% url 'account_delete' %}" class="mt-4">
                {% csrf_token %}
                <fieldset class="fieldset">
                    <label class="label" for="confirm_email">
                        Para confirmar, digite <span class="font-mono">{{ request.user.email }}</span>
                    </label>
                    <input type="email" name="confirm_email" id="confirm_email"
                           class="input w-full {% if error %}input-error{% endif %}"
                           autocomplete="off" autocapitalize="none" inputmode="email"
                           placeholder="{{ request.user.email }}" required>
                </fieldset>
                <button type="submit" class="btn btn-error mt-4" data-pending="Excluindo…">
                    Excluir minha conta para sempre
                </button>
            </form>
        </div>
    </section>
</div>
```

- [ ] **Step 6: Write the goodbye page and register both URLs**

Create `src/backend/templates/accounts/account_deleted.html`:

```html
{% extends "base_public.html" %}
{% comment %}
The one page a deleted account sees. Extends `base_public.html` because by the
time anyone gets here they have no session — `base.html` assumes a signed-in
user and half of it would redirect straight back to a login screen.
{% endcomment %}

{% block title %}Conta excluída — Expense Tracker{% endblock %}

{% block content %}
<div class="card bg-base-100 shadow-md max-w-md w-full">
    <div class="card-body items-center text-center">
        <div class="text-5xl mb-2">👋</div>
        <h1 class="card-title">Conta excluída</h1>
        <p class="text-base-content/70">
            Seus dados foram apagados. Obrigado por ter usado o Ledger — se um dia
            quiser voltar, é só criar uma conta nova.
        </p>
        <div class="card-actions mt-4">
            <a href="{% url 'account_login' %}" class="btn btn-ghost btn-sm">Voltar ao início</a>
        </div>
    </div>
</div>
{% endblock %}
```

In `src/backend/accounts/urls.py`, extend the import with `AccountDeleteView, AccountDeletedView` and add:

```python
    path("conta/privacidade/excluir/", AccountDeleteView.as_view(), name="account_delete"),
    path("conta/excluida/", AccountDeletedView.as_view(), name="account_deleted"),
```

- [ ] **Step 7: Exempt the goodbye page from the onboarding redirect**

`onboarding_redirect_middleware` only fires for a request with a `request.household`, and a deleted user has none — so `/casa/excluida/` is already safe. **Verify that rather than trusting it**, because the middleware runs before the view:

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_account_deletion_flow.py::TestTheGoodbyePage -q
```

Expected: 2 passed. If either 302s to `/casa/comecar/`, add `"/casa/excluida/"` to `_ONBOARDING_EXEMPT_PREFIXES` in `accounts/middleware.py:91` and re-run.

- [ ] **Step 8: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_account_deletion_flow.py -q
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_privacy_tab.py -q
```

Expected: both fully green — `test_it_offers_the_way_out` from Task 7 now passes too.

- [ ] **Step 9: Run the Quality Inspector**

`daisyui_quality_inspector`, `workflowId: e13-exclusao`, `auditIntent: "fix_changes"`, files `src/backend/templates/accounts/_privacy_delete.html` and `src/backend/templates/accounts/account_deleted.html`.

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/accounts/ src/backend/templates/accounts/
git commit -m "feat(E13): delete your account from the UI, with the export offered first"
```

---

## Task 9: Bounded retention — the purge job

**Files:**
- Create: `src/backend/core/privacy/retention.py`
- Modify: `src/backend/core/privacy/__init__.py`
- Modify: `src/backend/core/apps.py`
- Create: `src/backend/core/management/commands/purge_expired_data.py`
- Modify: `docs/runbook.md`
- Test: `src/backend/core/tests/test_privacy_retention.py`

**Interfaces:**
- Consumes: `core.privacy.purgeable`, `model_for` (Task 1); `core.tasks.task_handler`, `core.tasks.enqueue`.
- Produces:
  - `core.privacy.retention.PURGE_EXPIRED_DATA = "core.purge_expired_data"` — the task name.
  - `core.privacy.retention.purge_expired(as_of: date | None = None) -> dict[str, int]` — deletes what is due, returns per-model counts.
  - `core.privacy.retention.purge_expired_task(payload: dict) -> None` — the registered handler.
  - Management command `purge_expired_data`, with `--dry-run` and `--as-of YYYY-MM-DD`.

**This task builds the project's first scheduled job. There is nothing to copy.** The `expense-tracker-keepalive` Scheduler job was **deleted on 2026-08-14** and replaced by a Cloud Monitoring uptime check; `gcloud scheduler jobs list` returns nothing today, and the `create` block still in `docs/runbook.md:716` is explicitly labelled history. Two commands — `sweep_stuck_import_jobs` and `emit_usage_metrics` — document a schedule that has never existed. Step 8 below therefore *provisions* a rail rather than joining one, and adopts those two orphans.

**Why the shape is what it is (D7, D8).** The service is deployed `--allow-unauthenticated`, so a new HTTP endpoint is a new thing to defend — `core/tasks/auth.py` exists because of exactly that. A **Cloud Run Job** runs the management command with the service's own identity and no public surface. The command **enqueues** rather than doing the work inline, which buys observability for free: every run is a `TaskRun` row with a status, an attempt count and a `last_error`, already visible in the admin (`core/admin.py:30`) and already covered by the runbook's dead-letter procedure. And because `enqueue` is idempotent on the payload's content hash (`core/tasks/enqueue.py:30-40`), putting the date in the payload makes the sweep **exactly once per day** with no extra machinery.

**And why a cron at all, given E12 said not to (D13).** `settings.py:553-555` records the objection: *a deletion that depends on our cron running is a deletion that does not happen.* It is correct, and it is why uploaded files are swept by a bucket lifecycle rule instead. But no lifecycle rule can delete a database row — here the choice is a cron or nothing. So the objection is answered by making a stopped cron **detectable**: a `TaskRun` row per run, a one-command check in the runbook, and the alert policy in Step 8.5. Do not skip 8.5. Without it this task reproduces exactly the failure E12 named.

**One thing to settle before Step 8.** `docs/runbook.md` contradicts itself on production's `CLOUD_TASKS_ENABLED`: line 581 lists `=1` in the deploy variables, line 1661 says `=0` "which is production today". It changes nothing about this task's code — both backends run the same handler through `run_task_run` — but it changes where the sweep executes. Resolve it and fix whichever line is wrong:

```bash
gcloud run services describe expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --format="value(spec.template.spec.containers[0].env)" | tr ',' '\n' | grep CLOUD_TASKS
```

If it is `0`, the Cloud Run Job does the work in its own process and the 600s task timeout in Step 8 is the bound that matters. If it is `1`, the job only enqueues and the *service* sweeps — inside `task_dispatch_view`'s `select_for_update` on the `TaskRun` row, held for the whole handler (`core/tasks/views.py:80-83`), against Cloud Run's 300s request ceiling. `BATCH` in the code below is what keeps that bounded either way, and it is the reason the deletes are chunked rather than issued as one statement.

**Where the handler lives, and why not in `core/tasks.py`.** `core.tasks` is already a *package* in this repo, so an app-level `core/tasks.py` module cannot exist. The handler therefore lives in `core/privacy/retention.py` and is registered by an import in `CoreConfig.ready()` — the same import-for-side-effect idiom `core/apps.py` already uses for `core.signals`.

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_privacy_retention.py`:

```python
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
    type(row)._base_manager.filter(pk=row.pk).update(
        created_at=FROZEN_NOW - timedelta(days=days)
    )
    return row


class TestChat:
    def test_a_message_older_than_ninety_days_is_deleted(self, household, user):
        from assistant.models import ChatMessage, MessageRole

        old = age(
            ChatMessage, 91, household=household, created_by=user, role=MessageRole.USER
        )

        purge_expired()

        assert not ChatMessage.objects.filter(pk=old.pk).exists()

    def test_a_message_inside_the_window_is_kept(self, household, user):
        from assistant.models import ChatMessage, MessageRole

        recent = age(
            ChatMessage, 89, household=household, created_by=user, role=MessageRole.USER
        )

        purge_expired()

        assert ChatMessage.objects.filter(pk=recent.pk).exists()

    def test_the_boundary_day_is_kept(self, household, user):
        """Exactly 90 days old is inside the promise, not outside it."""
        from assistant.models import ChatMessage, MessageRole

        edge = age(
            ChatMessage, 90, household=household, created_by=user, role=MessageRole.USER
        )

        purge_expired()

        assert ChatMessage.objects.filter(pk=edge.pk).exists()

    def test_purging_a_message_takes_its_receipt_draft_with_it(self, household, user):
        """Plan decision D12: `ReceiptDraft.chat_message` is CASCADE, and both
        are 90 days, so the cascade only ever removes something already due.
        Asserted so nobody later 'fixes' the cascade and quietly extends draft
        retention past what the notice says."""
        from assistant.models import ChatMessage, MessageRole, ReceiptDraft

        message = age(
            ChatMessage, 91, household=household, created_by=user, role=MessageRole.USER
        )
        draft = baker.make(
            ReceiptDraft, household=household, created_by=user, chat_message=message
        )

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
    @pytest.mark.parametrize(
        "record", purgeable(), ids=lambda r: r.label
    )
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
            **{
                record.timestamp_field: FROZEN_NOW
                - timedelta(days=record.retention_days + 1)
            }
        )

        purge_expired()

        assert not model._base_manager.filter(pk=row.pk).exists(), (
            f"{record.label} claims {record.retention_days} days and kept a row "
            "older than that"
        )

    def test_an_abandoned_import_is_purged_but_a_finished_one_is_not(
        self, household, user
    ):
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

    def test_the_as_of_date_can_be_moved_so_a_dry_run_can_look_ahead(
        self, household, user
    ):
        """`--as-of` in the command. An operator asking 'what would tomorrow's
        run delete?' should not have to change the clock to find out."""
        from assistant.models import ChatMessage, MessageRole

        message = age(
            ChatMessage, 89, household=household, created_by=user, role=MessageRole.USER
        )

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

        old = age(
            ChatMessage, 100, household=household, created_by=user, role=MessageRole.USER
        )

        call_command("purge_expired_data")

        assert not ChatMessage.objects.filter(pk=old.pk).exists()

    def test_dry_run_deletes_nothing(self, household, user):
        from django.core.management import call_command

        from assistant.models import ChatMessage, MessageRole
        from core.models import TaskRun

        old = age(
            ChatMessage, 100, household=household, created_by=user, role=MessageRole.USER
        )

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
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_privacy_retention.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'core.privacy.retention'`.

- [ ] **Step 3: Write the purge**

Create `src/backend/core/privacy/retention.py`:

```python
"""Deleting what we said we would delete, on the day we said we would.

Retention is the half of LGPD that has no user interface: nobody clicks
anything, and if this job silently stops running there is no error and no
complaint — just a database quietly keeping a year of somebody's conversations
after a document promised ninety days.

Two properties are therefore load-bearing:

  * every period comes from ``core.privacy.INVENTORY``, which the notice also
    renders, so the promise and the enforcement cannot disagree;
  * every run leaves a ``TaskRun`` row, so "did it run?" has an answer that is
    not "grep the logs".

The handler is registered from ``CoreConfig.ready`` rather than from a
``core/tasks.py`` module, because ``core.tasks`` is already a package here and
the two names cannot coexist.
"""

import logging
from datetime import timedelta

from django.utils import timezone

from core.privacy.inventory import model_for, purgeable
from core.tasks import task_handler

logger = logging.getLogger(__name__)

PURGE_EXPIRED_DATA = "core.purge_expired_data"

#: Deleted per statement. One household's ninety-first day is a handful of
#: rows, so this only matters the first time the job runs against a database
#: that has never been swept — which is exactly when an unbounded DELETE would
#: hold a lock for the length of a Cloud Run request timeout.
BATCH = 5000


def purge_expired(as_of=None) -> dict[str, int]:
    """Delete everything past its retention period. Returns per-model counts.

    ``as_of`` is injected rather than read, so a test can pin the day and an
    operator can ask "what would tomorrow's run delete?" without touching a
    clock. Same rule as ``docs/testing-conventions.md`` §1.
    """
    now = as_of or timezone.now()
    counts: dict[str, int] = {}

    for record in purgeable():
        model = model_for(record)
        cutoff = now - timedelta(days=record.retention_days)
        # `_base_manager`, not `objects`: the household-scoped manager would
        # return none() outside a request, and a purge that silently deletes
        # nothing is worse than one that fails loudly.
        due = model._base_manager.filter(
            **{f"{record.timestamp_field}__lt": cutoff}, **record.purge_filter
        )
        deleted = _delete_in_batches(model, due)
        if deleted:
            counts[record.label] = deleted

    logger.info("Retention sweep for %s deleted: %s", now.date(), counts or "nothing")
    return counts


def count_expired(as_of=None) -> dict[str, int]:
    """What a run right now *would* delete. Used by ``--dry-run``.

    Counts only the rows each record names — not what cascades off them — so
    the number is the one an operator can check against the table itself.
    """
    now = as_of or timezone.now()
    counts: dict[str, int] = {}
    for record in purgeable():
        model = model_for(record)
        cutoff = now - timedelta(days=record.retention_days)
        due = model._base_manager.filter(
            **{f"{record.timestamp_field}__lt": cutoff}, **record.purge_filter
        ).count()
        if due:
            counts[record.label] = due
    return counts


def _delete_in_batches(model, queryset) -> int:
    """Delete by primary-key slices, so no single statement is unbounded.

    A queryset slice cannot be deleted directly in Django, which is why this
    collects ids first.
    """
    total = 0
    while True:
        ids = list(queryset.values_list("pk", flat=True)[:BATCH])
        if not ids:
            return total
        removed, _ = model._base_manager.filter(pk__in=ids).delete()
        total += len(ids)
        if len(ids) < BATCH:
            return total


@task_handler(PURGE_EXPIRED_DATA, max_attempts=3)
def purge_expired_task(payload: dict) -> None:
    """The scheduled sweep.

    ``payload["as_of"]`` is a date string rather than "now" so that the task's
    content hash differs per day — which is what makes ``enqueue`` idempotent
    per day rather than forever (plan decision D8).

    Raises on failure, which is the documented signal that earns a retry
    (`assistant/tasks.py:38-42`). Three attempts, because the work is
    idempotent: a partial sweep re-run deletes what is left and nothing twice.
    """
    # `datetime.UTC`, not `timezone.utc` — Django removed the latter in 5.0.
    from datetime import UTC, datetime

    raw = payload.get("as_of")
    as_of = (
        datetime.fromisoformat(raw).replace(tzinfo=UTC) if raw else timezone.now()
    )
    purge_expired(as_of=as_of)
```

- [ ] **Step 4: Register the handler and export the API**

In `src/backend/core/apps.py`, inside `ready()`, **before** `autodiscover()`:

```python
        # Imported for the side effect of registering the retention sweep.
        # `core.tasks` is a package here, so `core` cannot have the
        # `core/tasks.py` module that `autodiscover` would otherwise find.
        from core.privacy import retention  # noqa: F401
```

In `src/backend/core/privacy/__init__.py`, add:

```python
from core.privacy.retention import PURGE_EXPIRED_DATA, count_expired, purge_expired
```

```python
    "PURGE_EXPIRED_DATA",
    "count_expired",
    "purge_expired",
```

- [ ] **Step 5: Write the command**

Create `src/backend/core/management/commands/purge_expired_data.py`:

```python
"""Delete everything past its retention period (E13 S13-3).

Named `purge_expired_data`, deliberately not `retention_*`: this repo already
has `retention_report`, which is about E14's *cohort* retention. Two meanings of
"retention" one tab-completion apart is a foot-gun.

Runs as a Cloud Run Job on a daily Cloud Scheduler trigger — see
docs/runbook.md, "Retenção de dados (E13)". It enqueues rather than sweeping
inline so the run leaves a `TaskRun` row: an operator asking "did last night's
purge happen?" gets a row with a status instead of a log search.
"""

from datetime import UTC, date, datetime, time

from django.core.management.base import BaseCommand, CommandError

from core.privacy.retention import PURGE_EXPIRED_DATA, count_expired


class Command(BaseCommand):
    help = "Apaga dados cujo prazo de retenção venceu."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Só mostra o que seria apagado. Não apaga nada e não enfileira nada.",
        )
        parser.add_argument(
            "--as-of",
            type=str,
            default=None,
            help="Faz as contas como se hoje fosse esta data (AAAA-MM-DD).",
        )

    def handle(self, *args, **options):
        from django.utils import timezone

        if options["as_of"]:
            try:
                as_of = date.fromisoformat(options["as_of"])
            except ValueError as exc:
                raise CommandError("--as-of precisa ser AAAA-MM-DD.") from exc
        else:
            as_of = timezone.localdate()

        if options["dry_run"]:
            # `datetime.UTC`, not `timezone.utc` — Django removed the latter in
            # 5.0. Midnight, so `--as-of` means "at the start of that day".
            moment = datetime.combine(as_of, time.min, tzinfo=UTC)
            counts = count_expired(as_of=moment)
            self.stdout.write(f"== Venceriam em {as_of:%d/%m/%Y} ==")
            if not counts:
                self.stdout.write("Nada a apagar.")
                return
            for label, total in sorted(counts.items()):
                self.stdout.write(f"{label}: {total}")
            self.stdout.write("")
            self.stdout.write("Nada foi apagado — isto é um --dry-run.")
            return

        # Imported here so `--dry-run` never touches the queue.
        from core.tasks import enqueue

        task_run = enqueue(PURGE_EXPIRED_DATA, {"as_of": as_of.isoformat()})
        self.stdout.write(f"Varredura de {as_of:%d/%m/%Y} enfileirada: {task_run.pk}")
        self.stdout.write(f"Situação: {task_run.get_status_display()}")
```

- [ ] **Step 6: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_privacy_retention.py -q
```

Expected: all passed. The parameterized sweep runs once per purgeable record — twelve today — and skips the two that carry their own test.

- [ ] **Step 7: Prove the test can fail**

Change `record.retention_days` to `record.retention_days + 10_000` inside `purge_expired` and re-run. `TestChat::test_a_message_older_than_ninety_days_is_deleted` and the parameterized sweep must all go red. Put it back.

A retention test that passes whether or not anything is deleted is the second-most-dangerous artifact this epic could produce, after a deletion test with the same property. Do not skip this step.

- [ ] **Step 8: Write the runbook section**

In `docs/runbook.md`, immediately after the "Import and export jobs (E12)" section, add:

````markdown
## Retenção de dados (E13)

Every period this job enforces is declared in
`src/backend/core/privacy/inventory.py` and rendered by the privacy notice from
that same list. **Changing a period means editing the inventory** — never the
job, never the template. If you find a number in either, that is a bug.

Today: chat 90 days, rascunhos de cupom 90 days, importações abandonadas 180
days, exportações 180 days, convites 180 days, medição de uso 730 days,
eventos de produto 730 days, feedback 730 days, log de acesso administrativo
730 days, tentativas de login 30 days, `TaskRun` 90 days, sessões vencidas
imediatamente.

Uploaded CSVs and export archives are **not** in that list: those are deleted
by the bucket's own 7-day lifecycle rule (E12 decision 2), because a deletion
that depends on our cron running is a deletion that does not happen.

### What would tomorrow's run delete?

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py purge_expired_data --dry-run
```

Nothing is deleted and nothing is enqueued. Add `--as-of 2027-01-01` to ask the
same question about a future date.

### Run it by hand

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py purge_expired_data
```

It prints the `TaskRun` id. Under `CLOUD_TASKS_ENABLED=0` the handler has
already run in-process by the time the command returns.

### Did last night's run happen?

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from core.models import TaskRun
for run in TaskRun.objects.filter(name='core.purge_expired_data')[:7]:
    print(run.created_at.date(), run.status, run.payload.get('as_of'), run.last_error[:80])"
```

One row per day, `done`, empty error. A missing day means the Scheduler job did
not fire — check it before assuming the data was already clean.

### Provisioning the scheduled run (one-off, per environment)

**This is the first scheduled job this project has.** The old
`expense-tracker-keepalive` Scheduler job was deleted on 2026-08-14 in favour of
a Monitoring uptime check, so `gcloud scheduler jobs list` is empty and the
`create` block under *Cold starts* is history. Nothing here is "alongside" an
existing job.

A Cloud Run **Job**, not an HTTP endpoint. The service is deployed
`--allow-unauthenticated`, so every public path is a thing to defend; a job
runs the command with the service's own identity and adds no surface at all.

```bash
# 0. The API may have been left enabled from the deleted keepalive, or not.
#    Enabling an already-enabled API is a no-op, so just run it.
gcloud services enable cloudscheduler.googleapis.com run.googleapis.com \
  --project expense-tracker-482807

# 1. The job. Same image and same env as the service, --command overridden.
gcloud run jobs create ledger-purge \
  --project expense-tracker-482807 \
  --region southamerica-east1 \
  --image <the image the service currently runs> \
  --set-secrets <same as the service> \
  --set-env-vars <same as the service> \
  --command python \
  --args src/backend/manage.py,purge_expired_data \
  --max-retries 1 \
  --task-timeout 600s

# 2. The trigger. 03:20 local, when nobody is using the product.
gcloud scheduler jobs create http ledger-purge-daily \
  --project expense-tracker-482807 \
  --location southamerica-east1 \
  --schedule "20 3 * * *" \
  --time-zone "America/Sao_Paulo" \
  --uri "https://southamerica-east1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/expense-tracker-482807/jobs/ledger-purge:run" \
  --http-method POST \
  --oauth-service-account-email <the Cloud Run runtime service account> \
  --description "E13: apaga dados cujo prazo de retenção venceu"
```

The Scheduler service account needs `roles/run.invoker` on the job.

**Common failure:** the Scheduler job reports success while the Cloud Run job
fails. `:run` returns 200 as soon as the execution is *created*. The `TaskRun`
query above is the real check, which is the whole reason the command enqueues
instead of sweeping silently.

### Inspect an execution

```bash
gcloud run jobs executions list --job ledger-purge \
  --project expense-tracker-482807 --region southamerica-east1 --limit 5
```

### Alerting when it stops — do not skip this

E12 refused to let a cron own deletion, and its reasoning is on the record
(`settings.py:553-555`): *a deletion that depends on our cron running is a
deletion that does not happen*. Database rows have no lifecycle rule, so E13
has no alternative — which makes **detecting a stopped sweep** the whole of the
mitigation.

```bash
# Alert when a day passes with no successful purge. The log line comes from
# core.privacy.retention.purge_expired, which logs on every run including the
# ones that delete nothing.
gcloud logging metrics create ledger_purge_ran \
  --project expense-tracker-482807 \
  --description "One entry per completed retention sweep (E13)" \
  --log-filter='jsonPayload.message=~"Retention sweep for"'
```

Then, in Monitoring → Alerting, add a policy on `logging/user/ledger_purge_ran`
that fires when the count is **0 over 36 hours**, notifying the same channel as
the two existing policies (runbook § *The alert policies*). 36 rather than 24 so
one late run is not a page.

**Verify it the honest way:** disable the Scheduler job, wait for the window,
confirm the alert fires, re-enable. An alert nobody has seen fire is an
assumption.

### The two orphans, adopted

Until E13 there was no way to run a management command on a schedule at all, so
two commands have been documenting one they never had:

- `sweep_stuck_import_jobs` — "Schedule it next to the keepalive ping… once
  every 15 minutes is plenty" (`docs/runbook.md`, E12 section). The keepalive it
  points at was deleted in 2026-08-14.
- `emit_usage_metrics` — "Schedule the daily run with Cloud Scheduler against a
  Cloud Run job, or as a step in the existing cron path; **record whichever you
  pick here**" (E07 section). Never picked.

Both now have a rail. Create one Cloud Run Job each, on the pattern above —
`ledger-sweep-imports` on `*/15 * * * *`, `ledger-usage-metrics` daily at 03:40
— and **update those two runbook sections to say which was chosen**, since both
explicitly ask for that to be written down. Adopting them is not E13's
deliverable; leaving a rail behind that nobody knows exists would be the same
mistake twice.
````

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
POSTGRES_PORT=5433 uv run pytest src/backend/core/ -q
git add src/backend/core/ docs/runbook.md
git commit -m "feat(E13): bounded retention — a daily purge driven by the inventory"
```

---

## Task 10: The export is complete enough to be an access request

**Files:**
- Modify: `src/backend/finances/services/export_builder.py`
- Test: `src/backend/finances/tests/test_export_completeness.py` (create)

**Interfaces:**
- Consumes: `core.privacy.INVENTORY`, `Disposal` (Task 1); `build_export(household)` (`finances/services/export_builder.py:82`).
- Produces: `ledger.json` gains four keys — `conta`, `eventos`, `feedbacks`, `uso` — and `ARCHIVE_MEMBERS` is unchanged (no new files).

E12 already ships portability and already puts chat and memory rules in `ledger.json` (`export_builder.py:331-350`). What is missing is what two models' own docstrings promise: `core.ProductEvent` says it is *"exported by E13"* (`core/models.py:155`) and `core.Feedback` says it has *"its own entry on E13's processing inventory"* (`core/models.py:196-206`). Plus the account itself — an access request that omits "which email address, since when, which policy version you accepted" is not an access request.

`ledger.json`'s `"formato"` goes from `1` to `2`. Adding keys is backward-compatible for any reader, but the number is what tells a person which shape they are holding.

- [ ] **Step 1: Write the failing test**

Create `src/backend/finances/tests/test_export_completeness.py`:

```python
"""The archive is the access right, so it has to actually be complete.

E12 built the machinery and E13 consumes it — but two models say in their own
docstrings that E13 exports them, and until this task neither was in the file.
The test that matters here is the last one: it walks the inventory rather than
a list, so a model that starts holding personal data next year cannot quietly
stay out of the export.
"""

import io
import json
import zipfile

import pytest
from model_bakery import baker

from finances.services.export_builder import build_export

pytestmark = pytest.mark.django_db


def ledger(household) -> dict:
    archive = zipfile.ZipFile(io.BytesIO(build_export(household)))
    return json.loads(archive.read("ledger.json"))


class TestTheAccountItself:
    def test_the_address_and_the_name_are_in_it(self, household, user):
        user.first_name = "Vagner"
        user.save(update_fields=["first_name"])

        conta = ledger(household)["conta"]

        assert any(pessoa["email"] == "vagner@example.com" for pessoa in conta["pessoas"])
        assert any(pessoa["nome"] == "Vagner" for pessoa in conta["pessoas"])

    def test_the_household_and_the_role_are_in_it(self, household, user):
        conta = ledger(household)["conta"]
        assert conta["casa"]["nome"] == household.name
        assert conta["pessoas"][0]["papel"] == "owner"

    def test_the_accepted_policy_versions_are_in_it(self, household, user):
        from core.models import PolicyAcceptance, PolicyDocument

        PolicyAcceptance.objects.create(
            user=user, document=PolicyDocument.PRIVACY, version="2026-08-17"
        )

        aceites = ledger(household)["conta"]["aceites"]

        assert {"documento": "privacy", "versao": "2026-08-17"} in [
            {"documento": a["documento"], "versao": a["versao"]} for a in aceites
        ]

    def test_the_ai_consent_state_is_in_it(self, household, user):
        from core.privacy import set_ai_consent

        set_ai_consent(user, granted=True)

        consentimentos = ledger(household)["conta"]["consentimentos"]

        assert consentimentos[0]["finalidade"] == "ai_assistant"
        assert consentimentos[0]["concedido"] is True

    def test_no_password_hash_leaves_the_building(self, household, user):
        """An export is a file people email to themselves. A password hash in
        it is a credential in an inbox."""
        raw = json.dumps(ledger(household))
        assert user.password not in raw
        assert "pbkdf2" not in raw


class TestProductEvents:
    def test_they_are_exported(self, household, user):
        """`core.models.ProductEvent`'s own docstring says 'exported by E13'."""
        from core.events import EventName
        from core.models import ProductEvent

        ProductEvent.objects.create(
            household=household, user=user, name=EventName.ACTIVATED, once=True
        )

        eventos = ledger(household)["eventos"]

        assert any(evento["nome"] == "activated" for evento in eventos)

    def test_a_neighbours_events_are_not(self, household, other_household, other_user):
        from core.events import EventName
        from core.models import ProductEvent

        ProductEvent.objects.create(
            household=other_household, user=other_user, name=EventName.SIGNUP
        )

        assert ledger(household)["eventos"] == []


class TestFeedback:
    def test_it_is_exported(self, household, user):
        from core.models import Feedback

        Feedback.objects.create(household=household, user=user, message="tá lento")

        feedbacks = ledger(household)["feedbacks"]

        assert feedbacks[0]["mensagem"] == "tá lento"

    def test_a_neighbours_feedback_is_not(self, household, other_household, other_user):
        from core.models import Feedback

        Feedback.objects.create(
            household=other_household, user=other_user, message="segredo"
        )

        assert ledger(household)["feedbacks"] == []


class TestUsage:
    def test_what_the_ai_cost_is_exported(self, household, user):
        from assistant.models import InteractionKind, UsageInteraction

        baker.make(
            UsageInteraction,
            household=household,
            user=user,
            kind=InteractionKind.TEXT,
            credits_charged=3,
        )

        uso = ledger(household)["uso"]

        assert uso[0]["creditos"] == 3
        assert uso[0]["tipo"] == "text"


class TestTheArchiveIsStillWhatE12Built:
    def test_the_same_files_are_in_it(self, household):
        from finances.services.export_builder import ARCHIVE_MEMBERS

        archive = zipfile.ZipFile(io.BytesIO(build_export(household)))
        assert set(archive.namelist()) == set(ARCHIVE_MEMBERS)

    def test_the_chat_and_the_memory_rules_are_still_there(self, household, user):
        """E12 decision 3. Regression guard: this task edits the same dict."""
        from assistant.models import ChatMessage, MessageRole

        ChatMessage.objects.create(
            household=household, created_by=user, role=MessageRole.USER, content="oi"
        )

        payload = ledger(household)

        assert payload["conversas"][0]["conteudo"] == "oi"
        assert "regras_memoria" in payload

    def test_the_format_number_went_up(self, household):
        assert ledger(household)["meta"]["formato"] == 2

    def test_the_readme_mentions_what_was_added(self, household):
        archive = zipfile.ZipFile(io.BytesIO(build_export(household)))
        readme = archive.read("LEIA-ME.txt").decode()
        assert "conta" in readme.lower()


class TestNothingPersonalIsLeftOut:
    def test_every_household_owned_model_holding_personal_data_is_in_the_archive(
        self, household
    ):
        """The completeness assertion, driven by the inventory rather than by a
        list here — so a model that starts holding personal data next year
        cannot quietly stay out of an access request.

        The mapping is explicit because a `ledger.json` key is a pt-BR word
        chosen for a person reading the file, not a model label. Adding a
        household-owned model with a lawful basis means adding a line here and
        a section to the builder, and the test says which.
        """
        from accounts.models import household_owned_models

        from core.privacy import Disposal, record_for

        exported_under = {
            "finances.Entry": "entradas",
            "finances.InstallmentPlan": "parcelamentos",
            "finances.Income": "receitas",
            "finances.Category": "categorias",
            "finances.PaymentMethod": "formas_pagamento",
            "finances.Budget": "orcamentos",
            "finances.SystemicExpense": "despesas_sistemicas",
            "finances.ImportJob": "importacoes",
            "finances.ExportJob": "exportacoes",
            "assistant.ChatMessage": "conversas",
            "assistant.MemoryRule": "regras_memoria",
            "assistant.MemoryEmbedding": "regras_memoria",
            "assistant.ReceiptDraft": "rascunhos_recibo",
            "assistant.UsageInteraction": "uso",
            "assistant.UsageRecord": "uso",
            "core.ProductEvent": "eventos",
            "core.Feedback": "feedbacks",
            "accounts.Invitation": "conta",
        }

        payload = ledger(household)
        missing = []
        for model in household_owned_models():
            record = record_for(model._meta.label)
            if record.disposal is Disposal.NONE:
                continue
            key = exported_under.get(model._meta.label)
            if key is None or key not in payload:
                missing.append(model._meta.label)

        assert not missing, (
            "these hold personal data and are not in the export — add a section "
            f"to export_builder.build_export and a line to this map: {missing}"
        )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_export_completeness.py -q
```

Expected: FAIL — `KeyError: 'conta'`.

- [ ] **Step 3: Extend the builder**

In `src/backend/finances/services/export_builder.py`, extend `build_export`'s function-local imports:

```python
    from accounts.models import Invitation, Membership
    from core.models import Consent, Feedback, PolicyAcceptance, ProductEvent
```

…and add the four sections to the `payload` dict, after `"importacoes"`:

```python
            # E13. The account itself: an access request that omits "which
            # address, since when, which version you accepted" is not one.
            # `password` is deliberately absent — an export is a file people
            # email to themselves, and a hash in an inbox is a credential in
            # an inbox.
            "conta": {
                "casa": {
                    "nome": household.name,
                    "criada_em": household.created_at,
                },
                "pessoas": [
                    {
                        "email": membership.user.email,
                        "nome": membership.user.first_name,
                        "papel": membership.role,
                        "entrou_em": membership.created_at,
                    }
                    for membership in Membership.objects.filter(household=household)
                    .select_related("user")
                    .order_by("created_at")
                ],
                "convites": [
                    {
                        "email": invitation.email,
                        "criado_em": invitation.created_at,
                        "aceito_em": invitation.accepted_at,
                        "cancelado_em": invitation.revoked_at,
                    }
                    for invitation in Invitation.objects.for_household(household).order_by(
                        "created_at"
                    )
                ],
                "aceites": [
                    {
                        "documento": acceptance.document,
                        "versao": acceptance.version,
                        "aceito_em": acceptance.accepted_at,
                    }
                    for acceptance in PolicyAcceptance.objects.filter(
                        user__memberships__household=household
                    ).order_by("accepted_at")
                ],
                "consentimentos": [
                    {
                        "finalidade": consent.purpose,
                        "concedido": consent.granted,
                        "concedido_em": consent.granted_at,
                        "retirado_em": consent.revoked_at,
                    }
                    for consent in Consent.objects.filter(
                        user__memberships__household=household
                    ).order_by("updated_at")
                ],
            },
            # E13. `core.ProductEvent`'s docstring has said "exported by E13"
            # since E14 shipped; this is that promise. No user content is in
            # here by construction — the model forbids it.
            "eventos": [
                {
                    "nome": event.name,
                    "criado_em": event.created_at,
                    "detalhes": event.metadata,
                }
                for event in ProductEvent.objects.for_household(household).order_by(
                    "created_at"
                )
            ],
            # E13. The one table that holds user-authored text on purpose.
            "feedbacks": [
                {"mensagem": item.message, "criado_em": item.created_at}
                for item in Feedback.objects.for_household(household).order_by("created_at")
            ],
            # E13. What the AI cost. Kept for 730 days under legítimo interesse,
            # so a person asking what we hold about them is entitled to see it.
            "uso": [
                {
                    "tipo": interaction.kind,
                    "faixa": interaction.tier,
                    "creditos": interaction.credits_charged,
                    "criado_em": interaction.created_at,
                }
                for interaction in UsageInteraction.objects.for_household(household).order_by(
                    "created_at"
                )
            ],
```

Add `UsageInteraction` to the existing `from assistant.models import ...` line at the top of `build_export`, and `ExportJob` is already available through `finances.models`.

Bump the format marker:

```python
            "meta": {
                "gerado_em": timezone.now().isoformat(),
                "domicilio": str(household.pk),
                # 2: E13 added `conta`, `eventos`, `feedbacks` and `uso`.
                # Adding keys breaks no reader, but the number is what tells a
                # person which shape they are holding.
                "formato": 2,
            },
```

- [ ] **Step 4: Update the README inside the archive**

In `_readme()`, replace the `ledger.json` line of the "O que tem aqui" block with:

```
ledger.json             Tudo acima, sem perder nenhum campo, mais o histórico
                        de conversas com o assistente, as regras de memória, o
                        registro das importações, os dados da sua conta (quem
                        está na casa, quais versões dos documentos você aceitou,
                        se autorizou o uso de IA), os eventos de uso do produto,
                        os comentários que você enviou e quanto o assistente
                        custou em créditos.
```

- [ ] **Step 5: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/finances/tests/test_export_completeness.py -q
POSTGRES_PORT=5433 uv run pytest src/backend/finances/ -q
```

Expected: both green. E12's own export tests assert `ARCHIVE_MEMBERS` and the CSV contents; neither changes here.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/finances/
git commit -m "feat(E13): the export carries the account, the events, the feedback and the cost"
```

---

## Task 11: A privacy notice and terms that describe this product

**Files:**
- Create: `src/backend/core/privacy/subprocessors.py`
- Create: `src/backend/core/views_legal.py`
- Create: `src/backend/templates/legal/base_legal.html`
- Create: `src/backend/templates/legal/privacidade.html`
- Create: `src/backend/templates/legal/termos.html`
- Modify: `src/backend/config/settings.py`
- Modify: `src/backend/config/urls.py`
- Modify: `src/backend/accounts/middleware.py`
- Modify: `src/backend/templates/base_public.html`
- Modify: `src/backend/core/privacy/__init__.py`
- Modify: `.env.example`
- Test: `src/backend/core/tests/test_legal_pages.py`

**Interfaces:**
- Consumes: `core.privacy.INVENTORY`, `Basis`, `purgeable` (Task 1); `settings.PRIVACY_POLICY_VERSION`, `TERMS_VERSION` (Task 2).
- Produces:
  - `core.privacy.subprocessors.SubProcessor` — frozen dataclass: `name`, `role`, `receives`, `country`, `url`.
  - `core.privacy.subprocessors.SUBPROCESSORS: tuple[SubProcessor, ...]`.
  - `settings.PRIVACY_CONTROLLER` — dict with `name`, `cnpj`, `address`, `email`.
  - URL names `privacy_notice` → `/privacidade/`, `terms_of_service` → `/termos/`.
  - A `--deploy` system check, `E13.001`, that fails when the controller block is blank.

> **This is the task the epic warns about.** *"The failure mode here is a generic template that describes a product this is not. Every claim must match the implementation. If the policy and the code disagree, the code is the violation."* The defence built into this task is that the purposes table, the lawful-basis table and the retention table are **rendered from `core.privacy.INVENTORY`**, not typed. Only the prose around them is written by hand, and the tests below check each of its factual claims against the code.

- [ ] **Step 1: Run the daisyUI Blueprint chain, steps 1–4**

`workflowId: e13-legal`. Component Syntax Expert for: `table`, `card`, `alert`, `link`, `divider`, `badge`. Skip Creative Director and Page Architect.

- [ ] **Step 2: Write the failing test**

Create `src/backend/core/tests/test_legal_pages.py`:

```python
"""The notice says what the code does — asserted, not hoped.

Most of this file is unusual for a test suite: it reads a rendered legal
document and checks its factual claims against the implementation. That is the
point. A privacy notice is the only document in this repository that is
simultaneously marketing copy, a legal instrument and a description of a
system, and only the third of those can be tested.

What is NOT tested here is whether the document is legally sufficient. That is
the DoD item no engineer can close.
"""

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from core.privacy import Basis, purgeable
from core.privacy.subprocessors import SUBPROCESSORS

pytestmark = pytest.mark.django_db


@pytest.fixture
def notice():
    return Client().get(reverse("privacy_notice")).content.decode()


@pytest.fixture
def terms():
    return Client().get(reverse("terms_of_service")).content.decode()


class TestBothDocumentsArePublic:
    def test_the_notice_needs_no_account(self):
        """Somebody deciding whether to sign up has to be able to read it."""
        response = Client().get(reverse("privacy_notice"))
        assert response.status_code == 200

    def test_the_terms_need_no_account(self):
        assert Client().get(reverse("terms_of_service")).status_code == 200

    def test_a_signed_in_user_mid_onboarding_is_not_redirected_away(self, user, new_household):
        """`onboarding_redirect_middleware` 302s every non-exempt GET for a
        household that has not finished setup — which is every new signup, and
        exactly the person most likely to click 'Aviso de Privacidade' on the
        form they are filling in."""
        client = Client()
        client.force_login(user)
        assert client.get(reverse("privacy_notice")).status_code == 200
        assert client.get(reverse("terms_of_service")).status_code == 200

    def test_both_are_reachable_from_the_public_footer(self):
        body = Client().get(reverse("account_login")).content.decode()
        assert reverse("privacy_notice") in body
        assert reverse("terms_of_service") in body


class TestTheControllerIsNamed:
    def test_the_notice_names_the_controller(self, notice, settings):
        """LGPD art. 9 and art. 41: the notice must identify the controller and
        give a channel. A document that does neither is not a notice."""
        assert settings.PRIVACY_CONTROLLER["name"] in notice
        assert settings.PRIVACY_CONTROLLER["cnpj"] in notice

    def test_the_notice_gives_a_contact_for_privacy_questions(self, notice, settings):
        assert settings.PRIVACY_CONTROLLER["email"] in notice

    def test_it_says_what_the_deadline_is(self, notice):
        """15 days, LGPD art. 19. Printed where the person making the request
        can read it, not only in the runbook."""
        assert "15 dias" in notice

    def test_it_addresses_the_dpo_question_rather_than_ignoring_it(self, notice):
        assert "Encarregado" in notice


class TestEveryClaimAboutProcessing:
    def test_every_purpose_in_the_inventory_appears(self, notice):
        """Rendered from `core.privacy.INVENTORY`, so this cannot pass by
        accident — but it can fail loudly if someone hardcodes the table."""
        from core.privacy import INVENTORY, Disposal

        for record in INVENTORY:
            if record.disposal is Disposal.NONE:
                continue
            # First clause only: the notice wraps long purposes across cells.
            head = record.purpose.split(".")[0][:40]
            assert head in notice, f"{record.label}'s purpose is missing from the notice"

    def test_every_lawful_basis_is_cited_with_its_article(self, notice):
        for basis in Basis:
            assert basis.label in notice
            assert basis.article in notice

    def test_every_retention_period_appears(self, notice):
        for record in purgeable():
            if record.retention_days == 0:
                continue
            assert str(record.retention_days) in notice

    def test_it_says_content_goes_to_an_llm_provider_and_names_it(self, notice):
        """S13-4, and the single most important disclosure in the document."""
        assert "OpenAI" in notice

    def test_it_says_photos_and_audio_are_discarded(self, notice):
        """True today — `assistant/views.py:288` processes and drops them — and
        the one genuinely good privacy property this product already had."""
        assert "descartad" in notice

    def test_it_names_every_sub_processor(self, notice):
        for processor in SUBPROCESSORS:
            assert processor.name in notice

    def test_it_states_the_rights_lgpd_grants(self, notice):
        for right in ("acesso", "correção", "portabilidade", "exclusão", "anonimização"):
            assert right in notice.lower()

    def test_it_says_consent_for_the_ai_can_be_withdrawn_and_where(self, notice):
        assert "retirar" in notice.lower()
        assert reverse("account_privacy_tab") in notice


class TestTheClaimsMatchTheCode:
    def test_the_chat_period_it_prints_is_the_one_the_purge_uses(self, notice):
        from core.privacy import record_for

        assert str(record_for("assistant.ChatMessage").retention_days) in notice

    def test_it_does_not_promise_a_deletion_the_code_does_not_do(self, notice):
        """The notice must not claim the ledger is erased when a member leaves
        — plan decision D1 keeps it for the household, and saying otherwise
        would be a false statement about a system this test can read."""
        assert "continua com a casa" in notice or "permanece com a casa" in notice

    def test_it_carries_the_version_that_signup_records(self, notice):
        assert settings.PRIVACY_POLICY_VERSION in notice


class TestTheTerms:
    def test_they_carry_their_version(self, terms):
        assert settings.TERMS_VERSION in terms

    def test_they_describe_the_service(self, terms):
        assert "Ledger" in terms

    def test_they_cover_payment_even_though_nothing_is_charged_yet(self, terms):
        """S13-4 asks for terms 'covering the service, payment (forward-looking
        to E15), and termination'. Beta-is-free is a term, not the absence of
        one."""
        assert "grat" in terms.lower()

    def test_they_cover_termination_on_both_sides(self, terms):
        assert "encerrar" in terms.lower()

    def test_they_do_not_pretend_this_is_a_bank(self, terms):
        """The product is a bookkeeping tool. Any claim otherwise would be both
        false and regulated."""
        assert "não é" in terms and "instituição financeira" in terms


class TestTheControllerCannotShipBlank:
    def test_the_deploy_check_fails_when_the_controller_is_empty(self, settings):
        from django.core.checks import Error

        from core.checks_privacy import check_privacy_controller

        settings.PRIVACY_CONTROLLER = {"name": "", "cnpj": "", "address": "", "email": ""}
        problems = check_privacy_controller(None)

        assert problems
        assert isinstance(problems[0], Error)
        assert problems[0].id == "E13.001"

    def test_it_passes_when_the_controller_is_filled_in(self, settings):
        from core.checks_privacy import check_privacy_controller

        settings.PRIVACY_CONTROLLER = {
            "name": "Alguma Coisa LTDA",
            "cnpj": "00.000.000/0001-00",
            "address": "Rua Um, 1 — Fortaleza/CE",
            "email": "privacidade@exemplo.com",
        }
        assert check_privacy_controller(None) == []
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_legal_pages.py -q
```

Expected: FAIL — `NoReverseMatch: Reverse for 'privacy_notice' not found`.

- [ ] **Step 4: Write the sub-processor list**

Create `src/backend/core/privacy/subprocessors.py`:

```python
"""Every third party that receives personal data, and what it receives.

S13-6. Kept in code rather than only in a document because the privacy notice
renders it and `docs/architecture/data-inventory.md` is checked against it — one
list, three readers, no chance of the notice naming a vendor the product does
not use or missing one it does.

Every entry here was verified against the codebase at 65a1c7d. Adding a vendor
means adding a row here *and* saying so in the notice, which the tests enforce.
"""

from dataclasses import dataclass
from enum import StrEnum


class Country(StrEnum):
    BR = "Brasil"
    US = "Estados Unidos"


@dataclass(frozen=True)
class SubProcessor:
    name: str
    role: str
    receives: str
    country: Country
    url: str


SUBPROCESSORS: tuple[SubProcessor, ...] = (
    SubProcessor(
        name="OpenAI",
        role="Processamento de linguagem, visão e transcrição",
        receives=(
            "O texto que você escreve ao assistente, o áudio que você grava e as "
            "fotos de cupom que você envia, junto com o histórico recente da "
            "conversa e as suas regras de memória."
        ),
        country=Country.US,
        url="https://openai.com/policies/privacy-policy",
    ),
    SubProcessor(
        name="Google Cloud",
        role="Hospedagem (Cloud Run), fila de tarefas e armazenamento de arquivos",
        receives=(
            "Tudo que o aplicativo guarda, porque é onde ele roda: o servidor, "
            "os arquivos de importação e exportação e os registros de acesso."
        ),
        country=Country.BR,
        url="https://cloud.google.com/terms/cloud-privacy-notice",
    ),
    SubProcessor(
        name="Supabase",
        role="Banco de dados PostgreSQL gerenciado",
        receives="O banco de dados inteiro: lançamentos, conversas, conta.",
        country=Country.US,
        url="https://supabase.com/privacy",
    ),
    SubProcessor(
        name="Resend",
        role="Envio de e-mail transacional",
        receives=(
            "Seu endereço de e-mail e o conteúdo das mensagens do sistema — "
            "confirmação de cadastro, redefinição de senha, convites."
        ),
        country=Country.US,
        url="https://resend.com/legal/privacy-policy",
    ),
    SubProcessor(
        name="Sentry",
        role="Registro de erros da aplicação",
        receives=(
            "O tipo do erro, o arquivo e a linha. Nunca o conteúdo das suas "
            "requisições, dos seus lançamentos ou das suas conversas — isso é "
            "removido antes do envio."
        ),
        country=Country.US,
        url="https://sentry.io/privacy/",
    ),
    SubProcessor(
        name="Logfire",
        role="Rastreamento das chamadas do assistente",
        receives="Duração, modelo usado e custo de cada chamada de IA.",
        country=Country.US,
        url="https://pydantic.dev/legal/privacy",
    ),
)
```

> **Before writing this file, verify the vendor list against the repo you actually have.** Run:
> ```bash
> grep -rn "SENTRY_DSN\|OPENAI_API_KEY\|RESEND_API_KEY\|GS_BUCKET_NAME\|LOGFIRE\|SUPABASE" src/backend/config/settings.py .env.example
> ```
> Every hit must have a row above, and every row must have a hit. If Logfire is disabled in this deployment, keep the row and say so in the notice — a person is entitled to know a vendor is configured even if it is currently dark. If a vendor appears that is not listed here, add it; the tests will fail until the notice names it too.

- [ ] **Step 5: Settings, the deploy check, and the URLs**

In `src/backend/config/settings.py`, beside `PRIVACY_POLICY_VERSION` (Task 2):

```python
# Who is legally answerable for this data (LGPD art. 5º, VI and art. 41). Read
# from the environment so a fork or a staging deployment cannot accidentally
# publish a notice naming somebody else. `manage.py check --deploy` fails when
# any of these is blank — see core/checks_privacy.py.
PRIVACY_CONTROLLER = {
    "name": os.environ.get("PRIVACY_CONTROLLER_NAME", ""),
    "cnpj": os.environ.get("PRIVACY_CONTROLLER_CNPJ", ""),
    "address": os.environ.get("PRIVACY_CONTROLLER_ADDRESS", ""),
    "email": os.environ.get("PRIVACY_CONTACT_EMAIL", ""),
}
```

Create `src/backend/core/checks_privacy.py`:

```python
"""A deploy check, so the notice cannot go live half-filled.

Django's check framework rather than a startup assertion: `--deploy` is already
in this project's Definition-of-Done vocabulary (`INDEX.md` §7), and a check
that runs there is a check somebody actually runs.

A notice that says "Controlador: " with nothing after it is worse than no
notice — it looks compliant and identifies nobody.
"""

from django.conf import settings
from django.core.checks import Error, Tags, register

REQUIRED = ("name", "cnpj", "address", "email")


@register(Tags.security, deploy=True)
def check_privacy_controller(app_configs, **kwargs):
    blank = [
        key for key in REQUIRED if not (settings.PRIVACY_CONTROLLER.get(key) or "").strip()
    ]
    if not blank:
        return []
    return [
        Error(
            "The privacy notice has no controller: "
            f"{', '.join(blank)} {'is' if len(blank) == 1 else 'are'} blank.",
            hint=(
                "Set PRIVACY_CONTROLLER_NAME, PRIVACY_CONTROLLER_CNPJ, "
                "PRIVACY_CONTROLLER_ADDRESS and PRIVACY_CONTACT_EMAIL. LGPD art. 41 "
                "requires the controller to be identified and reachable; a notice "
                "that names nobody is not a notice."
            ),
            id="E13.001",
        )
    ]
```

Register it by importing from `CoreConfig.ready()`, beside the retention import:

```python
        # Imported for the side effect of registering the deploy check.
        from core import checks_privacy  # noqa: F401
```

Create `src/backend/core/views_legal.py`:

```python
"""The two documents, served to anyone.

Public on purpose and by necessity: somebody deciding whether to sign up has to
be able to read them, and the signup form links both. `TemplateView` with no
`LoginRequiredMixin`, and both paths are added to
`accounts.middleware._ONBOARDING_EXEMPT_PREFIXES` — otherwise a signed-in user
mid-setup, which is every new account, would be redirected away from the notice
they just clicked.

Everything factual comes from `core.privacy`. The prose is hand-written; the
purposes, the lawful bases, the retention periods and the sub-processors are
rendered from the same lists the code enforces.
"""

from django.conf import settings
from django.views.generic import TemplateView

from core.privacy import INVENTORY, Basis, Disposal, purgeable
from core.privacy.subprocessors import SUBPROCESSORS


class PrivacyNoticeView(TemplateView):
    template_name = "legal/privacidade.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["controller"] = settings.PRIVACY_CONTROLLER
        context["version"] = settings.PRIVACY_POLICY_VERSION
        context["purposes"] = [
            record for record in INVENTORY if record.disposal is not Disposal.NONE
        ]
        context["bases"] = list(Basis)
        # `retention_days == 0` is the expired-session sweep — true, and not
        # something to put in a table of promises about how long we keep things.
        context["retentions"] = [
            record for record in purgeable() if record.retention_days
        ]
        context["subprocessors"] = SUBPROCESSORS
        return context


class TermsView(TemplateView):
    template_name = "legal/termos.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["controller"] = settings.PRIVACY_CONTROLLER
        context["version"] = settings.TERMS_VERSION
        return context
```

In `src/backend/config/urls.py`, add the import and two routes near the top of `urlpatterns`, after `feedback/`:

```python
from core.views_legal import PrivacyNoticeView, TermsView
```

```python
    # Public by necessity (E13 S13-4): the signup form links both, and somebody
    # deciding whether to sign up has to be able to read them.
    path("privacidade/", PrivacyNoticeView.as_view(), name="privacy_notice"),
    path("termos/", TermsView.as_view(), name="terms_of_service"),
```

In `src/backend/accounts/middleware.py`, add two entries to `_ONBOARDING_EXEMPT_PREFIXES`:

```python
    # E13. Every new signup has an unonboarded household, and every new signup
    # is exactly who clicks these links from the form they are filling in.
    "/privacidade/",
    "/termos/",
```

- [ ] **Step 6: Write the shared legal layout and the footer**

Create `src/backend/templates/legal/base_legal.html`:

```html
{% extends "base_public.html" %}
{% comment %}
A long document inside `base_public.html`, whose `main` centres its child with
`items-center`. `self-start` on this wrapper is not styling: without it a
document taller than the viewport has its top clipped in a centred flex
container, which is the classic way a legal page loses its first paragraph.
{% endcomment %}

{% block shell %}
<article class="w-full max-w-3xl mx-auto self-start py-10 px-2 space-y-6">
    {% block document %}{% endblock %}
    <footer class="divider"></footer>
    <p class="text-xs opacity-60">
        <a href="{% url 'privacy_notice' %}" class="link">Aviso de Privacidade</a>
        ·
        <a href="{% url 'terms_of_service' %}" class="link">Termos de Uso</a>
    </p>
</article>
{% endblock %}
```

In `src/backend/templates/base_public.html`, immediately before `{% include "partials/_submit_guard.html" %}`:

```html
    {# E13. Reachable from the login and signup screens, which is where somebody #}
    {# deciding whether to trust this product is standing.                       #}
    <footer class="fixed bottom-0 inset-x-0 py-3 text-center text-xs opacity-60">
        <a href="{% url 'privacy_notice' %}" class="link link-hover">Aviso de Privacidade</a>
        <span class="mx-1">·</span>
        <a href="{% url 'terms_of_service' %}" class="link link-hover">Termos de Uso</a>
    </footer>
```

- [ ] **Step 7: Write the privacy notice**

Create `src/backend/templates/legal/privacidade.html`:

```html
{% extends "legal/base_legal.html" %}
{% comment %}
The tables are rendered from `core.privacy.INVENTORY` and
`core.privacy.subprocessors.SUBPROCESSORS`. Do not type a purpose, a lawful
basis, a retention period or a vendor name into this file: the whole design of
E13 is that the document and the code read the same list, and a hardcoded row
is exactly the drift this epic exists to prevent.

The prose between the tables IS hand-written, and every factual claim in it is
asserted by `core/tests/test_legal_pages.py`. If you change a sentence there,
expect a test to have an opinion.
{% endcomment %}

{% block title %}Aviso de Privacidade — Ledger{% endblock %}

{% block document %}
<header>
    <h1 class="text-3xl font-semibold">Aviso de Privacidade</h1>
    <p class="text-sm opacity-70 mt-2">
        Versão <span class="font-mono">{{ version }}</span>.
        Este documento explica o que o Ledger guarda sobre você, por quê, por quanto
        tempo, com quem compartilha e o que você pode exigir a qualquer momento.
    </p>
</header>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">1. Quem é responsável</h2>
    <p>
        O controlador dos seus dados, na definição da Lei Geral de Proteção de Dados
        (Lei 13.709/2018, art. 5º, VI), é:
    </p>
    <p class="not-prose">
        <strong>{{ controller.name }}</strong><br>
        CNPJ {{ controller.cnpj }}<br>
        {{ controller.address }}
    </p>
    <p>
        Para qualquer assunto de privacidade — pedido de acesso, correção,
        portabilidade, exclusão, ou uma dúvida sobre este documento — escreva para
        <a href="mailto:{{ controller.email }}" class="link">{{ controller.email }}</a>.
        Respondemos em até <strong>15 dias</strong>, que é o prazo do art. 19 da LGPD.
    </p>
    <p class="text-sm opacity-80">
        <strong>Encarregado (DPO).</strong> A Resolução CD/ANPD nº 2/2022 dispensa
        agentes de tratamento de pequeno porte de indicar um encarregado formal, e o
        Ledger se enquadra nessa categoria hoje. Mesmo assim, o endereço acima é um
        canal de comunicação mantido para exatamente esse fim, como a mesma resolução
        exige. Se isso mudar, este documento muda junto.
    </p>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">2. O que guardamos, e para quê</h2>
    <p>
        A tabela abaixo é gerada a partir do próprio código do Ledger. Não é uma
        descrição aproximada: é a lista das tabelas que existem no banco de dados,
        com a finalidade de cada uma.
    </p>
    <div class="overflow-x-auto">
        <table class="table table-sm table-zebra">
            <thead>
                <tr><th>O quê</th><th>Para quê</th><th>Base legal</th></tr>
            </thead>
            <tbody>
                {% for record in purposes %}
                <tr>
                    <td class="font-mono text-xs whitespace-nowrap">{{ record.label }}</td>
                    <td>{{ record.purpose }}</td>
                    <td class="whitespace-nowrap text-xs">
                        {{ record.basis.label }}<br>
                        <span class="opacity-60">{{ record.basis.article }}</span>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">3. As bases legais, em português</h2>
    <ul class="space-y-3">
        <li>
            <strong>{{ bases.0.label }} ({{ bases.0.article }}).</strong>
            A escrituração em si — seus lançamentos, suas receitas, suas categorias,
            seus orçamentos, sua conta e as cópias de segurança do banco de dados.
            Você se cadastrou para ter um caderno de contas; guardar o caderno é o
            contrato. Não pedimos permissão para isso porque é o serviço.
        </li>
        <li>
            <strong>{{ bases.1.label }} ({{ bases.1.article }}).</strong>
            O assistente de IA: o texto que você escreve, o áudio que você grava, as
            fotos de cupom, as regras que ele aprende com as suas correções e os
            vetores derivados delas. Isso sai do Ledger e vai para a
            <strong>OpenAI</strong>, e por isso é uma escolha sua, separada do
            cadastro. Você pode
            <a href="{% url 'account_privacy_tab' %}" class="link">retirar essa
            autorização</a> quando quiser, e o resto do aplicativo continua
            funcionando exatamente igual.
        </li>
        <li>
            <strong>{{ bases.2.label }} ({{ bases.2.article }}).</strong>
            Registros que existem para o serviço não ser derrubado nem usado de má-fé:
            tentativas de login que falharam, quanto cada uso de IA custou, quando um
            administrador abriu uma tela com dados de cliente, e a contagem de passos
            do produto. Nada disso guarda o que você escreveu.
        </li>
    </ul>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">4. Por quanto tempo</h2>
    <p>
        Também gerado a partir do código. Uma rotina automática roda todo dia e apaga
        o que passou do prazo — não é uma intenção, é um trabalho agendado.
    </p>
    <div class="overflow-x-auto">
        <table class="table table-sm">
            <thead><tr><th>O quê</th><th>Prazo</th></tr></thead>
            <tbody>
                {% for record in retentions %}
                <tr>
                    <td>{{ record.purpose }}</td>
                    <td class="whitespace-nowrap">{{ record.retention_days }} dias</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    <p class="text-sm opacity-80">
        O que não está nesta tabela — seus lançamentos, suas categorias, as regras de
        memória do assistente — fica enquanto a sua conta existir, porque é o próprio
        conteúdo do serviço. Você apaga tudo isso a qualquer momento excluindo a
        conta.
    </p>
    <p class="text-sm opacity-80">
        Arquivos de importação e de exportação são um caso à parte: eles são apagados
        do armazenamento em <strong>7 dias</strong> por uma regra do próprio bucket,
        que roda independentemente do nosso sistema.
    </p>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">5. Com quem compartilhamos</h2>
    <p>
        Ninguém compra, aluga ou recebe seus dados para fins próprios. As empresas
        abaixo processam dados <em>em nome do Ledger</em>, para que ele funcione, e
        estão sujeitas aos contratos de cada uma:
    </p>
    <div class="overflow-x-auto">
        <table class="table table-sm table-zebra">
            <thead>
                <tr><th>Empresa</th><th>Para quê</th><th>O que recebe</th><th>Onde</th></tr>
            </thead>
            <tbody>
                {% for processor in subprocessors %}
                <tr>
                    <td class="whitespace-nowrap">
                        <a href="{{ processor.url }}" class="link" rel="noopener"
                           target="_blank">{{ processor.name }}</a>
                    </td>
                    <td>{{ processor.role }}</td>
                    <td>{{ processor.receives }}</td>
                    <td class="whitespace-nowrap">{{ processor.country }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    <p class="text-sm opacity-80">
        Parte dessas empresas fica fora do Brasil, o que a LGPD chama de transferência
        internacional (art. 33). Ela acontece porque é necessária para executar o
        contrato com você — no caso da OpenAI, porque foi você quem autorizou.
    </p>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">6. Fotos e áudio</h2>
    <p>
        Quando você fotografa um cupom ou grava um áudio, o arquivo é enviado para
        processamento e <strong>descartado em seguida</strong>. O Ledger nunca guarda a
        imagem nem o som — só o que foi extraído deles: os itens, os valores, o texto
        transcrito. Isso é assim desde antes deste documento existir, e continua
        sendo.
    </p>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">7. O que você pode exigir</h2>
    <p>A LGPD (art. 18) te dá estes direitos, e o Ledger os atende assim:</p>
    <ul class="list-disc list-inside space-y-1">
        <li>
            <strong>Acesso e portabilidade.</strong> Em
            <a href="{% url 'account_privacy_tab' %}" class="link">Conta → Privacidade</a>,
            botão “Baixar meus dados”: um .zip com tudo, em planilhas que o próprio
            Ledger importa de volta. Sem pedir para ninguém.
        </li>
        <li>
            <strong>Correção.</strong> Tudo que você vê no aplicativo, você edita. As
            conclusões que o assistente tirou sobre você estão listadas na mesma tela,
            uma a uma, com um botão para apagar cada uma.
        </li>
        <li>
            <strong>Exclusão e anonimização.</strong> Na mesma tela: “Excluir minha
            conta”. Apaga sua conta, suas conversas, as regras de memória e os
            rascunhos de cupom. Se você divide a casa com outra pessoa, o histórico
            financeiro <strong>continua com a casa</strong> — sem o seu nome em
            nenhum lançamento — porque também é dela. Se você é a única pessoa da
            casa, a casa inteira é apagada junto.
        </li>
        <li>
            <strong>Informação sobre compartilhamento.</strong> É a seção 5 acima.
        </li>
        <li>
            <strong>Revogação do consentimento.</strong> A autorização para o
            assistente de IA sai com um clique, na mesma tela, e o resto do aplicativo
            não muda.
        </li>
    </ul>
    <p>
        Se preferir pedir por escrito, escreva para
        <a href="mailto:{{ controller.email }}" class="link">{{ controller.email }}</a>.
        Respondemos em até 15 dias.
    </p>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">8. Segurança e incidentes</h2>
    <p>
        O acesso ao aplicativo exige senha, com verificação em duas etapas disponível
        para qualquer conta. As senhas são guardadas como hash — nem nós conseguimos
        lê-las. O tráfego é criptografado. Os dados de uma casa são isolados dos de
        outra no banco de dados, e isso é verificado por testes automatizados a cada
        alteração.
    </p>
    <p>
        Se acontecer um incidente de segurança que possa te causar risco relevante,
        avisamos você e a ANPD. O prazo que seguimos é de <strong>72 horas</strong> a
        partir do momento em que tomamos conhecimento.
    </p>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">9. Crianças e adolescentes</h2>
    <p>
        O Ledger não é destinado a menores de 18 anos e não coleta dados de crianças
        conscientemente. Se descobrirmos uma conta assim, ela é excluída.
    </p>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">10. Mudanças neste aviso</h2>
    <p>
        Cada versão tem uma data, e o Ledger registra qual versão você aceitou e
        quando — dá para conferir em
        <a href="{% url 'account_privacy_tab' %}" class="link">Conta → Privacidade</a>.
        Se uma mudança for relevante, avisamos por e-mail antes de ela valer.
    </p>
    <p class="text-sm opacity-60">
        Versão <span class="font-mono">{{ version }}</span>.
    </p>
</section>
{% endblock %}
```

- [ ] **Step 8: Write the terms**

Create `src/backend/templates/legal/termos.html`:

```html
{% extends "legal/base_legal.html" %}
{% comment %}
Terms of service. Deliberately short and specific to what this product is: a
bookkeeping tool for a household, free during the beta, that is not a bank and
does not touch anybody's money.

S13-4 asks for "the service, payment (forward-looking to E15), and
termination". Section 5 is written so that E15 changes a price, not a promise.
{% endcomment %}

{% block title %}Termos de Uso — Ledger{% endblock %}

{% block document %}
<header>
    <h1 class="text-3xl font-semibold">Termos de Uso</h1>
    <p class="text-sm opacity-70 mt-2">
        Versão <span class="font-mono">{{ version }}</span>. Ao criar uma conta no
        Ledger você concorda com o que está aqui.
    </p>
</header>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">1. Quem oferece o serviço</h2>
    <p class="not-prose">
        <strong>{{ controller.name }}</strong><br>
        CNPJ {{ controller.cnpj }}<br>
        {{ controller.address }}<br>
        <a href="mailto:{{ controller.email }}" class="link">{{ controller.email }}</a>
    </p>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">2. O que o Ledger é</h2>
    <p>
        Um aplicativo para registrar e acompanhar as contas de uma casa: lançamentos,
        receitas, cartões, orçamentos, parcelas e uma projeção dos próximos meses. Tem
        um assistente que lê cupom fiscal por foto e entende pedidos em português.
    </p>
    <p>
        O Ledger <strong>não é</strong> uma instituição financeira, não é um banco, não
        movimenta dinheiro, não se conecta à sua conta bancária e não dá consultoria
        de investimentos. Ele anota o que você diz que aconteceu. As decisões
        financeiras são suas.
    </p>
    <p>
        O assistente usa modelos de IA e pode errar — ler um valor errado num cupom,
        classificar uma compra na categoria errada. Por isso todo lançamento vindo de
        uma foto passa por uma tela de confirmação antes de entrar. Confira.
    </p>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">3. Sua conta</h2>
    <ul class="list-disc list-inside space-y-1">
        <li>Você precisa ter 18 anos ou mais.</li>
        <li>
            Um endereço de e-mail é uma conta. Guarde a sua senha; se desconfiar que
            alguém a descobriu, troque-a e ative a verificação em duas etapas.
        </li>
        <li>
            Convidar alguém para a sua casa dá a essa pessoa acesso a todo o histórico
            financeiro dela. Convide com esse entendimento.
        </li>
        <li>
            Não use o serviço para nada ilegal, nem tente contornar os limites de uso,
            derrubá-lo ou extrair dados de outras pessoas.
        </li>
    </ul>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">4. Seus dados são seus</h2>
    <p>
        O que você registra continua sendo seu. Você pode baixar tudo a qualquer
        momento, em formato aberto, por
        <a href="{% url 'account_privacy_tab' %}" class="link">Conta → Privacidade</a>.
        O
        <a href="{% url 'privacy_notice' %}" class="link">Aviso de Privacidade</a>
        explica o que guardamos, por quanto tempo e com quem compartilhamos.
    </p>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">5. Preço</h2>
    <p>
        Durante o beta o Ledger é <strong>gratuito</strong>, com um limite mensal de
        uso do assistente. Passar do limite não te tira do ar: as funções de
        escrituração continuam, e o assistente responde num modo mais econômico ou
        avisa que o limite foi atingido.
    </p>
    <p>
        Um dia haverá um plano pago. Quando houver, avisaremos por e-mail com
        antecedência, e nada passa a ser cobrado sem você concordar explicitamente com
        o preço. Não haverá cobrança retroativa pelo período gratuito.
    </p>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">6. Disponibilidade</h2>
    <p>
        O serviço é oferecido “como está”, sem garantia de disponibilidade
        ininterrupta. Fazemos cópias de segurança do banco de dados, mas a única cópia
        que está sob o seu controle é a que você baixa — vale exportar de vez em
        quando.
    </p>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">7. Encerramento</h2>
    <p>
        Você pode <strong>encerrar</strong> sua conta quando quiser, em
        <a href="{% url 'account_privacy_tab' %}" class="link">Conta → Privacidade</a>,
        sem precisar falar com ninguém. A exclusão é imediata e não tem volta — baixe
        seus dados antes.
    </p>
    <p>
        Podemos <strong>encerrar</strong> ou suspender uma conta que use o serviço para
        algo ilegal, que tente comprometê-lo, ou que abuse dos limites de uso de forma
        sistemática. Nesse caso avisamos pelo e-mail cadastrado e damos um prazo
        razoável para você exportar seus dados, exceto quando a lei exigir o
        contrário.
    </p>
    <p>
        Se o serviço for descontinuado, avisamos com pelo menos 30 dias de
        antecedência para que todo mundo consiga levar seus dados embora.
    </p>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">8. Mudanças nestes termos</h2>
    <p>
        Cada versão tem uma data. Mudanças relevantes são avisadas por e-mail antes de
        valerem, e o Ledger registra qual versão você aceitou.
    </p>
</section>

<section class="space-y-2">
    <h2 class="text-xl font-semibold">9. Lei aplicável</h2>
    <p>
        Estes termos são regidos pelas leis brasileiras, incluindo o Código de Defesa
        do Consumidor e a Lei Geral de Proteção de Dados. Fica eleito o foro do
        domicílio do consumidor para resolver qualquer questão.
    </p>
    <p class="text-sm opacity-60">
        Versão <span class="font-mono">{{ version }}</span>.
    </p>
</section>
{% endblock %}
```

- [ ] **Step 9: Fill in the controller, and prove the check works**

Add to `.env.example`, under the `# --- Privacy (E13) ---` heading:

```
# LGPD art. 41 — the notice has to name somebody and give a channel.
# `manage.py check --deploy` fails (E13.001) when any of these is blank.
PRIVACY_CONTROLLER_NAME=
PRIVACY_CONTROLLER_CNPJ=
PRIVACY_CONTROLLER_ADDRESS=
PRIVACY_CONTACT_EMAIL=
```

Then put the real values in your local `.env` and confirm both states:

```bash
# Blank -> fails
DEBUG=False SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(50))") \
  ALLOWED_HOSTS=example.com PRIVACY_CONTROLLER_NAME= \
  uv run python src/backend/manage.py check --deploy 2>&1 | grep E13.001

# Filled -> passes
DEBUG=False SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(50))") \
  ALLOWED_HOSTS=example.com \
  uv run python src/backend/manage.py check --deploy
```

Expected: the first prints the `E13.001` line; the second reports no `E13.001`.

- [ ] **Step 10: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_legal_pages.py -q
POSTGRES_PORT=5433 uv run pytest src/backend/accounts/tests/test_signup_records_acceptance.py -q
```

Expected: both fully green. Task 3's two link tests pass now that the URLs are real.

The `TestTheControllerIsNamed` tests read `settings.PRIVACY_CONTROLLER`, so they pass with whatever is configured — including blanks, since `"" in text` is trivially true. **That is a real hole**, so add this to the class and make it pass:

```python
    def test_the_controller_is_not_blank_in_this_environment(self, settings):
        """Guards the three tests above, which would otherwise pass vacuously:
        `"" in anything` is True."""
        for key in ("name", "cnpj", "address", "email"):
            assert settings.PRIVACY_CONTROLLER[key].strip(), (
                f"PRIVACY_CONTROLLER[{key!r}] is blank — set it in .env, and see "
                "core/checks_privacy.py"
            )
```

- [ ] **Step 11: Run the Quality Inspector**

`daisyui_quality_inspector`, `workflowId: e13-legal`, `auditIntent: "fix_changes"`, files `src/backend/templates/legal/base_legal.html`, `privacidade.html`, `termos.html`, `src/backend/templates/base_public.html`. The authored spacing on a long document is a recorded deviation — **do not** convert the sections to cards to satisfy a house-style finding.

- [ ] **Step 12: Read both documents in a browser at 390px and 1440px**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py runserver 8700
```

Open `/privacidade/` and `/termos/`. Check three things a test cannot: the first paragraph is not clipped (that is what `self-start` is for), the tables scroll horizontally instead of pushing the page sideways, and both render in the dark theme.

**Then read the notice from top to bottom as a sceptic**, with `core/privacy/inventory.py` open beside it. Every sentence is a claim about this codebase. The tests check the ones a test can reach; this is how the rest get checked.

- [ ] **Step 13: Lint and commit**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add src/backend/core/ src/backend/config/ src/backend/accounts/middleware.py \
        src/backend/templates/legal/ src/backend/templates/base_public.html .env.example
git commit -m "feat(E13): a privacy notice and terms rendered from the code they describe"
```

---

## Task 12: The data-flow inventory, and verifying the error tracker against it

**Files:**
- Create: `docs/architecture/data-inventory.md`
- Create: `src/backend/core/tests/test_sentry_scrubbing.py`
- Modify: `src/backend/core/tests/test_privacy_inventory.py`

**Interfaces:**
- Consumes: `core.privacy.subprocessors.SUBPROCESSORS` (Task 11); `core.observability.scrub_event`, `sentry_settings` (`core/observability.py:19-124`).
- Produces: `docs/architecture/data-inventory.md`, kept beside the notice and enforced by a test in the same style as `core/tests/test_metrics_doc.py`.

This is S13-6. Its second clause is the one that matters: *"the error tracker's PII scrubbing is verified against this inventory, not assumed."* The inventory claims Sentry receives "the type of the error, the file and the line — never your content". That is a testable claim, and until it is tested it is a sentence.

- [ ] **Step 1: Write the failing test**

Create `src/backend/core/tests/test_sentry_scrubbing.py`:

```python
"""What the error tracker actually receives, checked against what we claim.

`docs/architecture/data-inventory.md` and the privacy notice both say Sentry
gets the shape of a failure and never its contents. `core.observability` was
built to make that true (ADR-005). This file is the difference between "was
built to" and "does".

The events below are hand-built in the shape the SDK emits, so no network and
no `sentry_sdk.init` are involved: `scrub_event` is a pure function, which is
exactly why it was written that way.
"""

import json

from core.observability import scrub_event, sentry_settings
from core.privacy.subprocessors import SUBPROCESSORS

#: The things this test hunts for in a scrubbed payload. Each one is a real
#: category of content from this product, written the way it would actually
#: appear — a chat message, an entry description, a receipt total, a session
#: cookie, an API key.
SECRETS = [
    "Comprei remédio na Pague Menos e paguei 87,43",
    "Salário da Amanda",
    "sessionid=abc123",
    "sk-proj-realkeydonotship",
    "vagner@example.com",
]


def an_event_carrying_everything() -> dict:
    """An event in the shape sentry-sdk builds for a Django request failure."""
    return {
        "level": "error",
        "request": {
            "url": "https://ledger.example.com/entries/",
            "method": "POST",
            "query_string": "month=2026-08",
            "data": {"description": SECRETS[0], "amount": "87.43"},
            "cookies": {"sessionid": "abc123"},
            "headers": {"Authorization": "Bearer sk-proj-realkeydonotship"},
            "env": {"REMOTE_ADDR": "203.0.113.7"},
        },
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": "invalid literal",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "finances/views/entries.py",
                                "lineno": 361,
                                "function": "post",
                                "vars": {
                                    "description": SECRETS[0],
                                    "income_name": SECRETS[1],
                                    "cookie": SECRETS[2],
                                    "api_key": SECRETS[3],
                                    "user": SECRETS[4],
                                },
                            }
                        ]
                    },
                }
            ]
        },
        "extra": {"chat_message": SECRETS[0], "user_email": SECRETS[4]},
        "breadcrumbs": {
            "values": [
                {
                    "category": "query",
                    "message": "SELECT",
                    "data": {"sql": f"INSERT INTO entry (description) VALUES ('{SECRETS[0]}')"},
                }
            ]
        },
    }


class TestNothingWeCallPrivateSurvives:
    def test_no_piece_of_user_content_is_anywhere_in_the_scrubbed_event(self):
        """One assertion over the whole serialized payload rather than one per
        key. A scrubber that misses a nesting level fails here even if every
        individual key it knows about is clean."""
        scrubbed = json.dumps(scrub_event(an_event_carrying_everything(), {}))
        leaked = [secret for secret in SECRETS if secret in scrubbed]
        assert not leaked, f"these reached the error tracker: {leaked}"

    def test_the_request_body_cookies_headers_and_env_are_gone(self):
        scrubbed = scrub_event(an_event_carrying_everything(), {})
        request = scrubbed["request"]
        for key in ("data", "cookies", "headers", "env"):
            assert key not in request

    def test_stack_frame_locals_are_gone(self):
        """The real leak path: the variable holding a chat message lives in the
        frame that raised."""
        scrubbed = scrub_event(an_event_carrying_everything(), {})
        frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
        assert "vars" not in frame

    def test_extra_and_breadcrumb_data_are_gone(self):
        scrubbed = scrub_event(an_event_carrying_everything(), {})
        assert "extra" not in scrubbed
        assert "data" not in scrubbed["breadcrumbs"]["values"][0]


class TestTheEventIsStillUseful:
    def test_the_url_the_method_and_the_query_string_survive(self):
        """A scrubbed event nobody can locate is as useless as no event."""
        scrubbed = scrub_event(an_event_carrying_everything(), {})
        assert scrubbed["request"]["url"].endswith("/entries/")
        assert scrubbed["request"]["method"] == "POST"
        assert scrubbed["request"]["query_string"] == "month=2026-08"

    def test_the_exception_type_the_file_and_the_line_survive(self):
        scrubbed = scrub_event(an_event_carrying_everything(), {})
        frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
        assert scrubbed["exception"]["values"][0]["type"] == "ValueError"
        assert frame["filename"] == "finances/views/entries.py"
        assert frame["lineno"] == 361


class TestTheConfigurationItself:
    def test_default_pii_is_off(self):
        """`send_default_pii=True` attaches request bodies, cookies and user
        identifiers wholesale — it would defeat the scrubber upstream of it."""
        config = sentry_settings({"SENTRY_DSN": "https://k@o0.ingest.sentry.io/1"})
        assert config["send_default_pii"] is False

    def test_the_scrubber_is_actually_wired_as_before_send(self):
        config = sentry_settings({"SENTRY_DSN": "https://k@o0.ingest.sentry.io/1"})
        assert config["before_send"] is scrub_event

    def test_no_dsn_means_nothing_is_transmitted_at_all(self):
        """The local-development and CI path, and it must transmit nothing."""
        assert sentry_settings({}) is None
        assert sentry_settings({"SENTRY_DSN": "   "}) is None

    def test_the_scrubber_never_raises_on_a_malformed_event(self):
        """It runs on every event. An exception here drops the event silently
        and the failure it described is lost twice over."""
        for weird in ({}, {"request": "not-a-dict"}, {"exception": []}, {"breadcrumbs": None}):
            scrub_event(weird, {})


class TestTheInventoryDocumentIsAContract:
    def test_it_exists(self):
        from pathlib import Path

        doc = (
            Path(__file__).resolve().parents[4]
            / "docs"
            / "architecture"
            / "data-inventory.md"
        )
        assert doc.is_file()

    def test_every_sub_processor_is_documented(self):
        """Same mechanism as `core/tests/test_metrics_doc.py`: the document is
        only a contract if something forces it to keep up."""
        from pathlib import Path

        doc = (
            Path(__file__).resolve().parents[4]
            / "docs"
            / "architecture"
            / "data-inventory.md"
        ).read_text(encoding="utf-8")
        missing = [p.name for p in SUBPROCESSORS if p.name not in doc]
        assert not missing, f"undocumented sub-processors: {missing}"

    def test_the_document_records_what_sentry_is_verified_not_to_receive(self):
        from pathlib import Path

        doc = (
            Path(__file__).resolve().parents[4]
            / "docs"
            / "architecture"
            / "data-inventory.md"
        ).read_text(encoding="utf-8")
        assert "test_sentry_scrubbing.py" in doc
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_sentry_scrubbing.py -q
```

Expected: FAIL — `TestTheInventoryDocumentIsAContract` fails on the missing file. **The scrubbing tests should pass immediately**, because E06 already built the scrubber. That is the good outcome and it is worth stating: this task's job is to *verify* a claim, and finding it already true is a pass, not a wasted task.

If any scrubbing test fails, that is a live privacy defect in production — fix `core/observability.py` here rather than weakening the assertion, and say so in the commit message.

- [ ] **Step 3: Write the inventory document**

Create `docs/architecture/data-inventory.md`:

```markdown
# Data inventory and data flows

**Owner:** E13 · LGPD compliance. **Kept beside** the privacy notice
(`src/backend/templates/legal/privacidade.html`), which renders the same lists.

Two things live here that do not fit in code:

- the **flow** — which data crosses which boundary, and what triggers it;
- the **evidence** — what has actually been verified, and by which test.

The lists themselves are code. `src/backend/core/privacy/inventory.py` holds
one record per model and `src/backend/core/privacy/subprocessors.py` holds one
per third party; both are rendered by the notice and enforced by
`src/backend/core/tests/test_privacy_inventory.py`. **Do not restate them
here** — a second copy of a list is how a notice starts describing a product
that no longer exists.

## Boundaries

Four, and nothing personal crosses any other.

| # | Boundary | What crosses it | When |
|---|---|---|---|
| 1 | Browser → Cloud Run (Google, `southamerica-east1`) | Everything the person types, photographs or records | Every request |
| 2 | Cloud Run → Supabase PostgreSQL | Every stored row | Every request that reads or writes |
| 3 | Cloud Run → OpenAI | Chat text, recent history, memory rules, receipt images, audio | Only when the person has granted AI consent, and only on an assistant turn |
| 4 | Cloud Run → Google Cloud Storage | Uploaded CSVs and generated export archives | Import and export jobs only |

Three more receive data that is *about* a person without being their content:

| # | Boundary | What crosses it |
|---|---|---|
| 5 | Cloud Run → Resend | Email address and the body of a transactional message |
| 6 | Cloud Run → Sentry | Exception type, file, line, URL, method, query string |
| 7 | Cloud Run → Logfire | Model name, latency, token counts, cost of an AI call |

## What boundary 3 actually sends, and what it does not

The disclosure that matters most, because it is the one people are surprised by.

**Sent:** the message text; the last `ASSISTANT_MAX_HISTORY` (20) turns of the
conversation; the household's memory rules that matched; the receipt image
bytes; the audio bytes.

**Not sent:** the ledger. The assistant reaches entries through tools that run
in Python and return computed answers, never a table dump — that is the money
boundary from `INDEX.md` §7.3, and it is a privacy property as much as a
correctness one.

**Not retained by us:** the image and the audio. Both are read into memory,
processed and dropped inside the request — the image at
`assistant/views.py:505` (`prepare_receipt_image(image.read(), ...)`), the audio
at `assistant/views.py:388-390` (`transcribe_audio(audio.read(), ...)`). Neither
path touches `core.storage` or writes a file anywhere. Only the extracted text
and values are stored. This predates E13 and is the one genuinely good privacy
property this product had before it had a privacy policy.

*(E13's epic file cites `assistant/views.py:288` for this. That line has moved
since the epic was written on 2026-08-07 — the two real sites are above.
Re-check them with `grep -n "\.read()" src/backend/assistant/views.py` before
trusting this paragraph, because it is a claim the privacy notice repeats.)*

**Gate:** `core.privacy.consent`. Verified by
`src/backend/assistant/tests/test_ai_consent_gate.py`, including that a refusal
opens no interaction and charges no credit.

## Boundary 6 — what Sentry is verified NOT to receive

The privacy notice claims Sentry gets the shape of a failure and never its
contents. That claim is **verified, not assumed**, by
`src/backend/core/tests/test_sentry_scrubbing.py`, which builds an event in the
SDK's own shape carrying a chat message, an entry description, a session
cookie, an API key and an email address, runs it through
`core.observability.scrub_event`, and asserts none of the five survives
anywhere in the serialized payload.

It also asserts what does survive — URL, method, query string, exception type,
file, line — because a scrubbed event nobody can locate is as useless as no
event, and a scrubber that passes by deleting everything would be a false pass.

Configuration facts the same file asserts: `send_default_pii` is `False`,
`before_send` really is `scrub_event`, and no DSN means nothing is transmitted
at all (the local-development and CI path).

**If a new integration is added to `sentry_sdk.init`, re-read this section.**
An integration can attach payloads the scrubber's key list does not know about;
the whole-payload assertion in that test is what catches it.

## Retention

Every period is declared in `core/privacy/inventory.py` and enforced daily by
`manage.py purge_expired_data` — see `docs/runbook.md`, "Retenção de dados
(E13)". Uploaded CSVs and export archives are **not** on that timer: the
bucket's own 7-day lifecycle rule deletes them, because a deletion that depends
on our cron running is a deletion that does not happen (E12 decision 2).

Account deletion does not wait for that rule. `core.privacy.deletion` collects
every `ImportJob.storage_key` and `ExportJob.storage_key` belonging to a
household it is about to remove, and deletes those blobs after the transaction
commits — so "your data is deleted" is true of the bucket as well as of
Postgres, and the lifecycle rule is only the backstop for one it missed.

**E13 is the first scheduled job this project has.** The cron objection E12
recorded is answered by making a stopped sweep detectable rather than by
assuming it will run: a `TaskRun` row per run, a log-based metric
(`ledger_purge_ran`) and an alert policy that fires after 36 hours with none.

## Contracts still outstanding

Engineering cannot close these. They are listed so nobody assumes they are done.

- [ ] **A DPA with OpenAI**, and confirmation that its retention policy does not
      contradict what the notice promises. Epic open question 5.
- [ ] **A DPA with Supabase and with Resend.**
- [ ] **Legal review of the notice and the terms by a Brazilian lawyer.** The
      Definition of Done's last item, and the one this repository cannot satisfy.

## Changing anything here

1. Add or edit the `Record` / `SubProcessor` in code.
2. The notice re-renders itself. Do not edit its tables.
3. Update the flow section above if a *boundary* changed, not if a field did.
4. `POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_privacy_inventory.py
   src/backend/core/tests/test_sentry_scrubbing.py -q` must be green.
```

- [ ] **Step 4: Add the document to the inventory's own contract test**

In `src/backend/core/tests/test_privacy_inventory.py`, append:

```python
def test_the_boundaries_document_exists_beside_the_notice():
    """S13-6: 'the inventory is kept with the privacy notice so both stay
    consistent'."""
    from pathlib import Path

    doc = Path(__file__).resolve().parents[4] / "docs" / "architecture" / "data-inventory.md"
    assert doc.is_file()
```

- [ ] **Step 5: Run the tests**

```bash
POSTGRES_PORT=5433 uv run pytest src/backend/core/tests/test_sentry_scrubbing.py \
  src/backend/core/tests/test_privacy_inventory.py -q
```

Expected: all passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add docs/architecture/data-inventory.md src/backend/core/tests/
git commit -m "docs(E13): the data-flow inventory, with the error tracker verified against it"
```

---

## Task 13: The two procedures, and walking one of them

**Files:**
- Modify: `docs/runbook.md`
- Create: `docs/superpowers/evidence/e13-breach-tabletop/README.md`

**Interfaces:**
- Consumes: `core.privacy.delete_account` (Task 6); `build_export` (Task 10); `core.AdminAccessLog`, `core.TaskRun`, `created_by` (E04/E05/E06).
- Produces: two runbook sections and one evidence file.

Two DoD items live here: *"`docs/runbook.md` contains the data-subject-request procedure with the 15-day deadline and the breach procedure with the 72-hour deadline"* and *"the breach tabletop exercise has been run once"*. The second is not a document — it is an afternoon, written down afterwards.

- [ ] **Step 1: Write the data-subject-request procedure**

In `docs/runbook.md`, immediately after the "Retenção de dados (E13)" section from Task 9, add:

````markdown
## Pedido de titular (LGPD) — 15 dias

Most requests need no operator at all: access, portability, correction and
deletion are all self-service in **Conta → Privacidade**. This section is for
the ones that arrive by email — because the person cannot sign in, because they
asked in writing, or because they want something the UI does not offer.

**The deadline is 15 days** from the request (LGPD art. 19). Not 15 business
days. Start by acknowledging, so the clock is visibly running.

### 0. Log it

Reply the same day:

> Recebemos seu pedido em <data>. Vamos responder até <data + 15 dias>, que é o
> prazo da LGPD. Se precisarmos confirmar sua identidade, escrevemos antes disso.

### 1. Identify the person, without creating a new risk

The address the request came from must match the account's, or you have no
business acting on it. **Do not** accept a photo of a document as proof — it
adds personal data you did not have and did not need. If the addresses do not
match, ask them to send the request from the address on the account.

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from core.models import CustomUser
p = CustomUser.objects.filter(email__iexact='PESSOA@example.com').first()
print(p, p and p.date_joined, p and [m.household.name for m in p.memberships.all()])"
```

### 2. Access or portability

Point them at **Conta → Privacidade → Baixar meus dados**. It is the same
archive you would build by hand, it is scoped to their household by
construction, and it arrives through a signed expiring link rather than through
your email client.

If they genuinely cannot sign in, build it and hand it over out of band:

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from accounts.resolution import household_for_user
from core.models import CustomUser
from finances.services.export_builder import build_export
p = CustomUser.objects.get(email__iexact='PESSOA@example.com')
open('/tmp/ledger-export.zip','wb').write(build_export(household_for_user(p)))
print('ok')"
```

Delete `/tmp/ledger-export.zip` when it has been collected. It is somebody's
complete financial history sitting on a disk.

### 3. Correction

Everything a person can see, they can edit. The one thing worth naming: the
assistant's inferences are listed individually in **Conta → Privacidade**, each
with its own delete button, and deleting one removes its embedding too.

### 4. Deletion

Self-service in **Conta → Privacidade → Excluir minha conta**, and prefer it:
the UI offers the export first, which is the part an operator forgets.

By hand, only when they cannot reach it:

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from core.models import CustomUser
from core.privacy import delete_account
p = CustomUser.objects.get(email__iexact='PESSOA@example.com')
print(delete_account(p))"
```

It prints a `DeletionReceipt`. **Keep it** — it is what you paste into the reply,
and it is the only record that survives, because the account it describes does
not.

What survives a deletion, and why, is stated in the privacy notice, section 7:
the household's ledger when somebody else is still in the house, and the
anonymised metering rows kept for 730 days under legítimo interesse.

### 5. Close it

Reply inside the 15 days, naming what was done. If a request is refused —
somebody asking to delete a household they do not own, say — say so plainly and
say why. An unanswered request is the failure the deadline exists to prevent.
````

- [ ] **Step 2: Write the breach procedure**

Immediately after that section:

````markdown
## Incidente de segurança — 72 horas

LGPD art. 48. The clock starts when you **become aware**, not when you finish
investigating. 72 hours is the target for notifying the ANPD and the affected
people, and the notification does not wait for a complete picture — an
incomplete notice on time beats a complete one late.

### Hour 0 — contain, then write down the time

Write down the moment you became aware, before doing anything else. Every
deadline below counts from it.

Contain in this order:

```bash
# 1. Rotate whatever might be exposed. The service reads secrets at start, so
#    a new revision is required for a rotation to take effect.
#    See "Transactional email" and "Async tasks" for the secret names.

# 2. If it is an application-level leak, roll back to the last good revision.
gcloud run services update-traffic expense-tracker \
  --project expense-tracker-482807 --region southamerica-east1 \
  --to-revisions <last-good-revision>=100

# 3. If credentials may be loose, end every session.
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from django.contrib.sessions.models import Session
print(Session.objects.all().delete())"
```

### Hours 0–24 — scope it

The question the ANPD asks is *whose* data, and *what* data. These are the
sources that can answer it, and they exist because earlier epics built them:

| Question | Where the answer is | From |
|---|---|---|
| Which requests, and from where? | Cloud Logging, filtered by `request_id` | E06 |
| Did staff read customer data? | `core.AdminAccessLog` — actor, path, timestamp | E05 S05-5 |
| Who wrote or changed a row? | `created_by` on every authored model | E04 |
| Which background work ran? | `core.TaskRun` — name, status, attempts, `request_id` | E10 |
| Which households could a leak have touched? | `household` on all 18 tenant tables | E04 phase 4 |
| Did an export leave? | `finances.ExportJob` — one row per archive built | E12 |

```bash
# Everything one request touched, across the app and its tasks.
gcloud logging read \
  'jsonPayload.request_id="<id>"' \
  --project expense-tracker-482807 --limit 200 --format json

# Staff access in a window.
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from datetime import timedelta
from django.utils import timezone
from core.models import AdminAccessLog
since = timezone.now() - timedelta(days=7)
for row in AdminAccessLog.objects.filter(created_at__gte=since):
    print(row.created_at, row.actor, row.method, row.path, row.ip)"

# Archives built in a window — each one is a household's whole history.
POSTGRES_PORT=5433 uv run python src/backend/manage.py shell -c "
from datetime import timedelta
from django.utils import timezone
from finances.models import ExportJob
since = timezone.now() - timedelta(days=7)
for job in ExportJob.objects.filter(created_at__gte=since):
    print(job.created_at, job.household_id, job.status, job.size_bytes)"
```

**A gap worth knowing before you need it.** There is no per-row read log. If the
question is "did anyone read Amanda's entries?", the honest answer for a
non-staff path is *we cannot tell from the data we keep* — and the notification
has to say that rather than imply otherwise. E17 is where a customer-data
access trail would live.

### Hours 24–72 — notify

Notify the **ANPD** at <https://www.gov.br/anpd> and the **affected people**
directly. The notice must carry, at minimum:

1. what data was involved;
2. how many people, and which categories;
3. what technical and security measures were in place;
4. the risks involved;
5. what has been done since, and what the person should do now;
6. why, if the notification is late.

Draft it in Portuguese, addressed to the person, not to a regulator. Send from
`{{ PRIVACY_CONTACT_EMAIL }}`.

### After — write it down

An incident that nobody wrote up happens again. Add a dated file under
`docs/superpowers/evidence/`, with the timeline, the scope, what was notified
and what changed as a result.
````

- [ ] **Step 3: Run the tabletop exercise — this is work, not a document**

Block ninety minutes. Pick the scenario that is actually plausible for this
product:

> **Scenario.** At 09:14 a beta user emails: "I opened the app and I'm looking
> at someone else's grocery entries." Sentry shows no errors. The last deploy
> was 40 minutes ago and touched `finances/views/`.

Walk it, out loud, against the procedure above, and **time yourself**. Do not
simulate the answers — actually run the commands against the dev database. The
exercise is worthless if the commands are read rather than executed, because
what it is really testing is whether they work.

Answer these, and write down how long each took:

1. Can you tell which revision is serving, and roll back? *(runbook, "Deploy")*
2. Can you find every request that user made in the last hour by `request_id`?
3. Can you tell whether any staff account read their data? *(AdminAccessLog)*
4. Can you list every household whose rows the suspect code path could reach?
5. Can you tell whether an export was built for anyone in that window?
6. **Can you actually answer "whose data was exposed"?** If not — and expect
   not — what is the smallest thing that would change that?
7. Could you draft the ANPD notification with what you have, inside 72 hours?

- [ ] **Step 4: Write down what happened**

Create `docs/superpowers/evidence/e13-breach-tabletop/README.md`:

```markdown
# Breach tabletop — <DATE>

**Scenario:** a beta user reports seeing another household's entries, 40 minutes
after a deploy touching `finances/views/`.

**Run by:** <name>. **Duration:** <minutes>.

**Method:** every command in `docs/runbook.md` § "Incidente de segurança" was
executed against the development database, not read.

## Timeline as walked

| Step | Command or source | Time taken | Worked? |
|---|---|---|---|
| Identify the serving revision | | | |
| Roll back | | | |
| Find the user's requests by `request_id` | | | |
| Check `AdminAccessLog` | | | |
| Enumerate households the code path could reach | | | |
| Check `ExportJob` in the window | | | |
| Draft the notification | | | |

## What worked

## What did not

## Gaps found, and what was done about each

| Gap | Severity | Action | Where it is tracked |
|---|---|---|---|

## The honest answer to "whose data was exposed"

<Write it. If the answer is "we cannot tell for a non-staff read path", say that
here in as many words — it is the finding, and the notification would have to
say the same thing.>

## Verdict

Could a notification have gone out inside 72 hours with what we have? Yes / No,
and why.
```

Fill every cell. A table of blanks is worse than no exercise, because it looks
like one was done.

- [ ] **Step 5: Act on what the exercise found**

Anything the exercise surfaced that is **cheap and inside this epic's scope**,
fix now and note it in the file. Anything larger — a per-row read log, for
instance — gets written into `docs/backlog/E17-trust-surface.md` as evidence,
with a pointer back to this file. Do not silently widen E13.

- [ ] **Step 6: Commit**

```bash
git add docs/runbook.md docs/superpowers/evidence/e13-breach-tabletop/
git commit -m "docs(E13): data-subject-request and breach procedures, and the tabletop that tested them"
```

---

## Task 14: Close the epic

**Files:**
- Modify: `src/backend/static/css/tailwind.css` (rebuilt)
- Modify: `docs/backlog/E13-lgpd-compliance.md`
- Modify: `docs/backlog/INDEX.md`
- Modify: `README.md`, `AGENTS.md` (runbook pointers)

- [ ] **Step 1: Rebuild the committed Tailwind CSS**

Tasks 3, 7, 8 and 11 added classes that have never been compiled — `toggle`,
`checkbox-error`, `table-zebra`, `self-start`, `border-error/30`. Without this
they do not exist, and the pages render subtly wrong in exactly one place each,
which reads as a template bug.

```bash
# Stop the watcher first if it is running, or it rewrites the file under you.
systemctl --user stop expense-tracker-js 2>/dev/null || true

uv run python src/backend/manage.py tailwind build --force
git add src/backend/static/css/tailwind.css
```

`--force` is not optional: Tailwind v4 trusts its cache and emits CSS missing
any class added since the last build. `mount.js` does **not** need rebuilding —
no task in this epic touched `src/backend/frontend/src/**` (the consent gate is
a 403 the existing widget already renders).

- [ ] **Step 2: Run the epic's Definition of Done, verbatim**

```bash
POSTGRES_PORT=5433 uv run coverage run -m pytest src/backend/ && uv run coverage report --fail-under=80
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
```

Both must pass. Then the rest of `INDEX.md` §7's verification vocabulary:

```bash
uv run python src/backend/manage.py makemigrations --check --dry-run
DEBUG=False SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(50))") \
  ALLOWED_HOSTS=example.com \
  uv run python src/backend/manage.py check --deploy
TEST_CLOCK_SHIFT=+1y POSTGRES_PORT=5433 uv run pytest src/backend/ -q -m "not current_date"
```

The clock-shifted run matters more in this epic than in any before it: retention
is arithmetic on dates, and a test that reads the wall clock will pass today and
fail in November. If the shifted run disagrees with the unshifted one, the fix
is to pin a date, not to pin the data (`docs/testing-conventions.md`).

> **One pre-existing failure is expected** and is not this epic's: a local
> `email_config` test that disagrees with the developer's `.env`. Confirm it
> fails identically at `65a1c7d` before dismissing it, and say so in the commit.

- [ ] **Step 3: Walk the whole thing once, as a person**

```bash
POSTGRES_PORT=5433 uv run python src/backend/manage.py runserver 8700
```

In order, with a fresh account:

1. Sign up. The checkbox is required; both links open.
2. Open the assistant. It refuses, in Portuguese, and says where to fix it.
3. Conta → Privacidade. Authorise. Ask the assistant something.
4. Correct a category so a memory rule appears. It shows up on the tab.
5. Delete that rule. It goes.
6. Withdraw the authorisation. The assistant refuses again. The dashboard,
   entries and projection all still work.
7. Baixar meus dados. Open the zip: `ledger.json` has `conta`, `eventos`,
   `feedbacks`, `uso`, and `meta.formato` is `2`.
8. Excluir minha conta. It offers the export, refuses the wrong address,
   accepts the right one, signs you out, and the goodbye page renders.
9. Try to sign in with the deleted account. It fails.

Then the shared case, which no single-account walkthrough reaches: invite a
second account, accept, delete the **owner**, and confirm the second account can
still sign in, still sees the ledger, and is now `Dono` on the Membros tab.

- [ ] **Step 4: Tick the epic's observable assertions**

In `docs/backlog/E13-lgpd-compliance.md`, tick each box with the evidence beside
it, and be honest about the last one:

```markdown
- [x] A user can export and then delete their account entirely from the UI —
      `accounts/tests/test_account_deletion_flow.py`, walked end to end
- [x] A test asserts no personal data survives deletion, parameterized across
      every model holding personal data — `core/tests/test_privacy_deletion.py`,
      parameterized from `core.privacy.INVENTORY`
- [x] Household deletion edge cases are implemented and tested — last owner
      promotes the longest-standing member; last member takes the household
- [x] The chat purge job runs on schedule and is tested —
      `core/tests/test_privacy_retention.py`; Cloud Run Job `ledger-purge`,
      runbook § "Retenção de dados (E13)"
- [x] The privacy notice's every factual claim has been checked against the
      implementation — `core/tests/test_legal_pages.py`; the purpose, basis and
      retention tables are rendered from `core.privacy.INVENTORY`
- [x] Signup records acceptance of a specific policy version —
      `accounts/tests/test_signup_records_acceptance.py`
- [x] `docs/runbook.md` contains the data-subject-request procedure with the
      15-day deadline and the breach procedure with the 72-hour deadline
- [x] The breach tabletop exercise has been run once —
      `docs/superpowers/evidence/e13-breach-tabletop/README.md`
- [x] The sub-processor inventory exists and matches the error tracker's
      scrubbing configuration — `docs/architecture/data-inventory.md`,
      verified by `core/tests/test_sentry_scrubbing.py`
- [ ] **A Brazilian lawyer has reviewed the privacy notice and terms** — NOT
      DONE. Engineering cannot close this. The documents are at
      `/privacidade/` and `/termos/`, version <VERSION>; the open contract
      questions are listed in `docs/architecture/data-inventory.md`.
```

Record the four decisions in the epic's "Open questions" section, replacing the
questions with the answers and a pointer to this plan.

- [ ] **Step 5: Update the backlog index**

In `docs/backlog/INDEX.md`:

- §4: E13's status `ready` → `done`, with a dated footnote.
- §3: R3's gate — three-quarters open becomes **all four conditions
  observably true**, *except* that the last one is qualified. Write it plainly:

  > **R3's fourth condition is engineering-complete as of <DATE>.** A data
  > subject can export, correct and delete their own data without contacting
  > anyone, retention is bounded and swept daily, and the notice is rendered
  > from the code it describes. **The gate does not open until a Brazilian
  > lawyer has reviewed the notice and the terms** — E13's own Definition of
  > Done says so, and it is the one item this repository cannot close.

- §4: E15 `blocked` → `ready`, since E07, E13 and E18 are now all closed. Note
  in the same edit that E15 inherits the qualification above: charging money
  before the legal review is exactly the risk E13 was written to remove.

- [ ] **Step 6: Point at the new runbook sections**

The user's standing rule: *a runbook nobody knows exists is not documentation.*
Add one line each.

`README.md`, in the quickstart's operations pointer:

```markdown
Privacidade e LGPD — retenção, pedidos de titular, resposta a incidente:
[`docs/runbook.md`](docs/runbook.md) §§ "Retenção de dados", "Pedido de
titular", "Incidente de segurança".
```

`AGENTS.md`, wherever it points at operator docs:

```markdown
- Anything touching personal data: read `docs/architecture/data-inventory.md`
  first, and add a `Record` to `src/backend/core/privacy/inventory.py` for any
  new model — the suite fails until you do.
```

- [ ] **Step 7: Final commit**

```bash
uv run ruff check src/backend/ && uv run ruff format --check src/backend/
git add -A
git commit -m "docs(E13): close the epic — ten assertions ticked, one left for a lawyer"
```

- [ ] **Step 8: Security review, then finish the branch**

E13 is on `INDEX.md` §5's list of security-touching epics, which insert
`/security-review` between the code review and the branch close. Run it on the
full diff. The two things to point it at explicitly:

- **Deletion completeness** — `core/privacy/deletion.py`. Does anything reach a
  person's data that the inventory does not classify?
- **Export authorization** — `finances/views/exporter.py` plus Task 10's four
  new sections. Can the `conta` section, which joins through
  `user__memberships__household`, surface a person who is not in this household?

Then `superpowers:requesting-code-review`, and
`superpowers:finishing-a-development-branch`.

---

## Self-review

Run against `docs/backlog/E13-lgpd-compliance.md` after the plan was complete.

### Spec coverage

| Spec element | Task | Notes |
|---|---|---|
| S13-1 · Account and household deletion | 5, 6, 8 | Export offered first (8); D1's household rules (6); parameterized survivor test (6) |
| S13-2 · Access, correction, portability | 7, 10 | Export reachable from the tab; memory rules shown and individually deletable; operator procedure in 13 |
| S13-3 · Bounded retention | 9 | Chat 90 days; drafts, imports, exports, usage all stated; scheduled, tested, observable via `TaskRun` |
| S13-4 · Notice and terms that are true | 2, 3, 11 | Rendered from the inventory; versioned; acceptance recorded at signup; pt-BR |
| S13-5 · Breach response readiness | 13 | Procedure + the tabletop actually walked, with the logging-gap answer written down |
| S13-6 · Sub-processor and data-flow inventory | 11, 12 | `SUBPROCESSORS` in code, rendered by the notice; Sentry scrubbing verified rather than assumed |
| DoD assertion 1–9 | 14 | Each ticked with named evidence |
| DoD assertion 10 (lawyer) | 14 | Explicitly left open — no task can close it |
| Open question 1 (lawful basis) | D3 | Contract + consent + legitimate interest |
| Open question 2 (DPO exemption) | 11 | ANPD Res. 2/2022 addressed in notice §1; channel kept regardless |
| Open question 3 (chat retention) | D2 | 90 days |
| Open question 4 (household deletion) | D1 | Member leaves, household survives, oldest member promoted |
| Open question 5 (OpenAI DPA) | 12 | Cannot be closed in code — listed under "Contracts still outstanding" |

Three things the epic did **not** ask for, added deliberately and flagged as
such: the consent revocation mechanism (D3a — required for D3's basis to be
truthful), the `UsageInteraction.user` fix (D10 — a latent data-loss bug found
while mapping the foreign keys), and blob deletion in `delete_account`
(without it, "your data is deleted" is true of Postgres and false of the bucket
for up to seven more days).

One thing the epic asked for that this plan **corrects rather than implements**:
its evidence row claiming `Entry.created_by` cascades. It does not, and has not
since E04 phase 4 — see "The epic's evidence table has one stale row".

### Corrections made after a second pass over the deployment state

Both were wrong in an earlier draft of this plan and are worth recording, since
the mistake is easy to repeat:

- **`docs/runbook.md:716` is not current state.** The `gcloud scheduler jobs
  create expense-tracker-keepalive` block sits inside a note that reads *"the
  rest of this section is history, kept for the recreate command"*. The job was
  deleted 2026-08-14 and replaced by a Monitoring uptime check. Task 9 therefore
  **creates** the project's first scheduled job rather than joining an existing
  rail, enables the API itself, and adopts the two commands
  (`sweep_stuck_import_jobs`, `emit_usage_metrics`) that have been documenting a
  schedule they never had.
- **E12 recorded an objection to crons owning deletion** (`settings.py:553-555`)
  and this plan has to answer it rather than route around it. D13 is that
  answer, and Step 8.5's alert policy is what makes it more than an assertion.

### Type and name consistency

Checked across tasks: `Record`, `Basis`, `Disposal`, `INVENTORY`, `record_for`,
`purgeable`, `model_for`, `subject_field`, `timestamp_field`, `purge_filter`,
`delete_account`, `DeletionReceipt`, `purge_expired`, `count_expired`,
`PURGE_EXPIRED_DATA`, `has_ai_consent`, `ahas_ai_consent`, `set_ai_consent`,
`AI_CONSENT_REQUIRED`, `SubProcessor`, `SUBPROCESSORS`, `PolicyDocument`,
`PolicyAcceptance`, `ConsentPurpose`, `Consent`, `LedgerSignupForm`,
`PrivacyTabView`, `AIConsentView`, `MemoryRuleDeleteView`, `AccountDeleteView`,
`AccountDeletedView`, `PrivacyNoticeView`, `TermsView`,
`check_privacy_controller`. URL names: `account_privacy_tab`,
`account_ai_consent`, `account_memory_rule_delete`, `account_delete`,
`account_deleted`, `privacy_notice`, `terms_of_service`.

### Ordering dependencies, stated rather than discovered

- Task 3 and Task 7 both reverse URL names Task 11 registers. Both say so, and
  both give the two-line stub to unblock in-order execution.
- Task 7 reverses `account_delete`, which Task 8 registers. Same treatment.
- Task 6 requires Task 5's migration; the deletion tests assert the SET_NULL
  behaviour directly, so running them out of order fails loudly rather than
  quietly.
- Task 4 will turn the existing `assistant` suite red. That is stated as the
  expected outcome, with the correct fix (a fixture) and the wrong one
  (defaulting consent to granted) both named.

