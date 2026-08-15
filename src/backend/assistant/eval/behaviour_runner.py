"""Drive the real assistant agent through a behavioural case and read the ledger.

The agent under test is ``assistant.agents.assistant.assistant_agent`` itself,
with its real tools and real prompt — anything less would test a copy of the
product rather than the product.

The clock is pinned per case (``case.today``) because billing-month judgment is
the point of half of them, and ``build_date_instructions`` injects the real date
into every run. ``time_machine`` is a dev dependency, imported lazily so that
importing this module never drags it into a production import graph.
"""

import time
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as clock_time

from asgiref.sync import sync_to_async
from django.utils import timezone

from assistant.agents.assistant import assistant_agent
from assistant.agents.model_compat import settings_for
from assistant.agents.scope import AgentScope
from assistant.eval.behaviour import BehaviourCase, LedgerRow


def build_world(case: BehaviourCase, household, user) -> None:
    """Create exactly what the case declares. Idempotent per household."""
    from assistant.models import ReceiptDraft, ReceiptDraftStatus
    from finances.models import Category, Entry, PaymentMethod

    categories: dict[str, Category] = {}
    for name in case.world.categories:
        categories[name], _ = Category.objects.get_or_create(
            household=household, name=name, defaults={"created_by": user}
        )
    methods: dict[str, PaymentMethod] = {}
    for spec in case.world.payment_methods:
        methods[spec.name], _ = PaymentMethod.objects.get_or_create(
            household=household,
            name=spec.name,
            defaults={
                "created_by": user,
                "type": spec.type,
                "closing_day": spec.closing_day,
            },
        )

    for raw in case.world.existing_entries:
        Entry.objects.create(
            household=household,
            created_by=user,
            date=date.fromisoformat(raw["date"]),
            amount=raw["amount"],
            description=raw["description"],
            category=categories[raw["category"]],
            payment_method=methods[raw["payment_method"]],
        )

    if case.world.registered_receipt is not None:
        ReceiptDraft.objects.create(
            household=household,
            created_by=user,
            payload=case.world.registered_receipt,
            status=ReceiptDraftStatus.REGISTERED,
        )
    if case.world.receipt_payload is not None:
        ReceiptDraft.objects.create(
            household=household,
            created_by=user,
            payload=case.world.receipt_payload,
            status=ReceiptDraftStatus.PENDING,
        )


def build_opening_prompt(case: BehaviourCase, scope) -> str:
    """The first prompt, built the way production builds it for that entry point."""
    from django.conf import settings

    from assistant.agents.extraction import (
        ReceiptExtraction,
        extraction_to_prompt,
        receipt_needs_review,
    )
    from assistant.agents.tools import (
        build_duplicate_receipt_directive,
        find_registered_duplicate,
    )

    if case.opening == "text":
        return case.turns[0]

    if case.opening == "receipt":
        ext = ReceiptExtraction(**case.world.receipt_payload)
        needs_review = receipt_needs_review(ext, settings.ASSISTANT_RECEIPT_MIN_CONFIDENCE)
        return extraction_to_prompt(ext, "", needs_review=needs_review)

    payload = case.world.registered_receipt
    dup = find_registered_duplicate(scope, payload)
    if dup is None:
        raise RuntimeError(
            f"{case.id}: the duplicate opening needs a REGISTERED draft that "
            "find_registered_duplicate can match — check World.registered_receipt "
            "and World.existing_entries."
        )
    return build_duplicate_receipt_directive(scope, payload, dup)


def _entry_ids(household) -> set:
    from finances.models import Entry

    return set(Entry.objects.for_household(household).values_list("id", flat=True))


def snapshot_ledger(household, before: set) -> list[LedgerRow]:
    """Rows that did not exist before the run, oldest first."""
    from finances.models import Entry

    qs = (
        Entry.objects.for_household(household)
        .exclude(id__in=before)
        .select_related("category", "payment_method")
        .order_by("created_at")
    )
    return [
        LedgerRow(
            category=e.category.name,
            amount=e.amount,
            billing_month=e.billing_month,
            payment_method=e.payment_method.name,
            description=e.description,
        )
        for e in qs
    ]


@dataclass(frozen=True)
class BehaviourRun:
    case_id: str
    rows: list[LedgerRow]
    usages: list[object]
    latency_ms: int
    error: str


async def run_behaviour_case(case: BehaviourCase, model, household, user) -> BehaviourRun:
    """Run every turn of one case and return the rows it created.

    Turns after the first are only sent while the agent is still answering; a
    run that errors stops there rather than replaying a broken conversation.
    """
    import time_machine  # dev dependency; see the module docstring

    scope = AgentScope(household=household, user=user)
    before = await sync_to_async(_entry_ids)(household)
    opening = await sync_to_async(build_opening_prompt)(case, scope)
    prompts = [opening, *(case.turns if case.opening != "text" else case.turns[1:])]

    usages: list[object] = []
    history = None
    error = ""
    started = time.perf_counter()
    destination = timezone.make_aware(datetime.combine(case.today, clock_time(12, 0)))
    with time_machine.travel(destination, tick=True):
        for prompt in prompts:
            try:
                result = await assistant_agent.run(
                    prompt,
                    deps=scope,
                    message_history=history,
                    model=model,
                    model_settings=settings_for(model),
                )
            except Exception as exc:  # noqa: BLE001 - a failed turn is data
                error = f"{type(exc).__name__}: {exc}"
                break
            usages.append(result.usage())
            history = result.all_messages()

    rows = await sync_to_async(snapshot_ledger)(household, before)
    return BehaviourRun(
        case_id=case.id,
        rows=rows,
        usages=usages,
        latency_ms=int((time.perf_counter() - started) * 1000),
        error=error,
    )
