"""The only way a ``ProductEvent`` gets written.

A function rather than direct ``objects.create`` calls so that the PII rule
(constraint 11: no user content in ``metadata``) has one place to be enforced
and reviewed, and so E14 can change what an event carries without visiting
every call site.
"""

from django.db import models

from core.models import ProductEvent


class EventName(models.TextChoices):
    """The funnel, from arrival to the moment the wedge lands.

    E14 (S14-2) extends this list. The values are stable strings because they
    are stored in rows that outlive any refactor — renaming one is a data
    migration, not an edit.
    """

    SIGNUP = "signup", "Cadastro"
    HOUSEHOLD_SEEDED = "household_seeded", "Casa preparada"
    ONBOARDING_STEP = "onboarding_step", "Passo do início"
    ONBOARDING_DONE = "onboarding_done", "Início concluído"
    FIRST_AI_ENTRY = "first_ai_entry", "Primeiro lançamento por IA"
    ACTIVATED = "activated", "Ativado"


#: Events that may happen at most once per household. Anything here is written
#: with ``once=True`` and is therefore covered by the partial unique index.
ONCE_PER_HOUSEHOLD = frozenset(
    {
        EventName.SIGNUP,
        EventName.HOUSEHOLD_SEEDED,
        EventName.ONBOARDING_DONE,
        EventName.FIRST_AI_ENTRY,
        EventName.ACTIVATED,
    }
)


def emit(name, *, household, user=None, metadata=None):
    """Record that ``name`` happened. Returns the row, or ``None`` if it could not.

    ``household is None`` is a no-op rather than an error: every scoped
    queryset in this codebase fails closed to ``none()`` for a household-less
    request, and an event writer must not be the one thing that raises instead.
    """
    if household is None:
        return None
    return ProductEvent.objects.create(
        household=household,
        name=str(name),
        user=user,
        once=name in ONCE_PER_HOUSEHOLD,
        metadata=metadata or {},
    )


def emit_once(name, *, household, user=None, metadata=None):
    """Record ``name`` only if this household has never had it.

    Returns the newly created row, or ``None`` when the household already had
    one. The return value is the "was this the first time?" answer — callers
    use it to decide whether to also emit a downstream event, so it must never
    be a truthy row on the second call.
    """
    if household is None:
        return None
    event, created = ProductEvent.objects.get_or_create(
        household=household,
        name=str(name),
        defaults={"user": user, "once": True, "metadata": metadata or {}},
    )
    return event if created else None
