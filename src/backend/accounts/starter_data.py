"""What a brand-new household starts with.

`Entry.category` is `PROTECT` and required, and so is `payment_method` — so a
household with an empty catalogue cannot record anything at all. That is the
first wall a stranger hits, and it is invisible: the form simply has no options.

The list is a trimmed subset of the production-derived catalogue in
`finances/management/commands/seed_data.py`, not an invention. The full
26-category version stays there: it is one real household's catalogue, built up
over months, and handing all of it to a stranger on day one is 26 decisions
before the first receipt. Twelve plus the two system categories covers the bulk
of Brazilian household spending, and everything here is editable and deletable.

Budget ceilings are deliberately absent. `seed_data.py` carries real ceilings
because they are the operator's real ceilings; copying them into a stranger's
ledger would put a made-up number on their dashboard on day one.
"""

from django.db import transaction

from core.events import EventName, emit_once
from finances.models import Category, PaymentMethod
from finances.models.payment_method import PaymentType

#: (name, is_system). The two system categories back `SystemicExpense` posting
#: and cannot be deleted — see `Category.delete`.
STARTER_CATEGORIES = [
    ("Alimentação", False),
    ("Lanche", False),
    ("Transporte", False),
    ("Combustível", False),
    ("Farmácia", False),
    ("Saúde", False),
    ("Casa", False),
    ("Lazer", False),
    ("Higiene", False),
    ("Limpeza", False),
    ("Serviços", False),
    ("Outros", False),
    ("Custeio", True),
    ("Financiamentos", True),
]

#: (name, type). No credit card: a card needs a closing day to put a purchase in
#: the right billing month, and guessing one silently misfiles every credit
#: purchase. The onboarding's card step asks for it and explains why (Task 6).
STARTER_PAYMENT_METHODS = [
    ("Dinheiro", PaymentType.CASH),
    ("Pix", PaymentType.PIX),
]


def seed_starter_data(household, user=None) -> dict:
    """Give ``household`` a usable catalogue. Idempotent.

    Returns how many rows were *created* — zero on every call after the first,
    which is what makes it safe to call from a signal that may fire twice.
    """
    from assistant.agents.scope import AgentScope
    from assistant.agents.tools import create_memory_rule
    from assistant.starter_rules import DEFAULT_RULES

    created = {"categories": 0, "payment_methods": 0, "rules": 0}

    # The catalogue is one unit: a household with categories but no payment
    # method still cannot record anything, so a half-seeded household is worse
    # than an unseeded one the command can repair.
    with transaction.atomic():
        for name, is_system in STARTER_CATEGORIES:
            _, was_created = Category.objects.get_or_create(
                household=household,
                name=name,
                defaults={"is_system": is_system, "created_by": user},
            )
            created["categories"] += int(was_created)

        for name, pm_type in STARTER_PAYMENT_METHODS:
            _, was_created = PaymentMethod.objects.get_or_create(
                household=household,
                name=name,
                defaults={"type": pm_type, "closing_day": None, "created_by": user},
            )
            created["payment_methods"] += int(was_created)

    # DELIBERATELY OUTSIDE the transaction above. `create_memory_rule` calls
    # `core.tasks.enqueue`, which calls `backend_for_settings().dispatch(...)`
    # synchronously with no `transaction.on_commit` — and with
    # CLOUD_TASKS_ENABLED that is a real HTTP push. A task delivered before the
    # `MemoryRule` row commits would look up a row that does not exist yet.
    # Today every `create_memory_rule` caller runs in autocommit
    # (`ATOMIC_REQUESTS` is off), so wrapping it here would introduce the race
    # rather than inherit it.
    #
    # Imported inside the function, not at module scope: `assistant.models`
    # already imports `accounts.models`, so an import the other way at module
    # level would be circular. Same reason `core/tiers.py` exists.
    scope = AgentScope(household=household, user=user)
    existing_triggers = {t.lower() for t in _memory_rule_triggers(household)}
    for trigger, category_name in DEFAULT_RULES:
        if trigger.lower() in existing_triggers:
            continue
        create_memory_rule(scope, trigger, "category", category_name)
        created["rules"] += 1

    emit_once(EventName.HOUSEHOLD_SEEDED, household=household, user=user, metadata=created)
    return created


def _memory_rule_triggers(household):
    """Triggers this household already has, so re-seeding creates nothing.

    `create_memory_rule` is an `update_or_create`, so calling it twice would not
    duplicate a row — but it *would* re-enqueue an embedding task and report a
    non-zero created count, and "idempotent" has to mean both.
    """
    from assistant.models import MemoryRule

    return MemoryRule.objects.for_household(household).values_list("trigger", flat=True)
