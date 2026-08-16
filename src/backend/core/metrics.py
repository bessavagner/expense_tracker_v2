"""Every product metric, once, as a function over querysets.

`retention_report` and `/metricas/` both call these, so "D7 retention" cannot
mean one thing on a terminal and another in a browser. What each number *means*
is decided in ``docs/architecture/product-metrics.md``; this module is only where
it is computed.

Nothing here writes. Nothing here reads the wall clock except through ``now``,
which every caller may inject — every one of these numbers is a function of
elapsed days, so a hidden ``timezone.now()`` is a test that drifts into passing
for the wrong reason.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

from core.events import EventName
from core.models import ProductEvent

#: The funnel, in the order a household walks it. Drop-off is the difference
#: between adjacent rows, which is only meaningful if the order is fixed here
#: rather than at each call site.
FUNNEL_ORDER = (
    EventName.SIGNUP,
    EventName.EMAIL_VERIFIED,
    EventName.HOUSEHOLD_SEEDED,
    EventName.ONBOARDING_STEP,
    EventName.ONBOARDING_DONE,
    EventName.RECEIPT_PHOTO,
    EventName.ACTIVATED,
)

#: `metadata.source` values that mean "the user did not type this in a form".
AI_SOURCES = frozenset({"receipt", "chat"})
#: ...and the one that means they did.
MANUAL_SOURCES = frozenset({"form"})
#: `import` is in neither: a CSV backfill is migration, not capture behaviour,
#: and one run of two thousand rows would swamp the ratio it is excluded from.


def _signup_rows(since=None):
    qs = ProductEvent.objects.filter(name=EventName.SIGNUP)
    if since is not None:
        qs = qs.filter(created_at__gte=since)
    return qs


def signup_cohorts(since=None) -> dict[date, list]:
    """Households grouped by the ISO week they signed up in, keyed by the Monday.

    Weekly rather than daily because a beta produces single-digit signups a day,
    and a cohort of one household is a coin flip rather than a retention rate.
    """
    cohorts: dict[date, list] = defaultdict(list)
    for household_id, created_at in _signup_rows(since).values_list("household_id", "created_at"):
        signup_day = timezone.localtime(created_at).date()
        monday = signup_day - timedelta(days=signup_day.weekday())
        cohorts[monday].append(household_id)
    return dict(cohorts)


def signup_times(household_ids) -> dict:
    """When each of these households signed up. The T0 of everything else."""
    return dict(
        ProductEvent.objects.filter(
            name=EventName.SIGNUP, household_id__in=list(household_ids)
        ).values_list("household_id", "created_at")
    )


def last_activity(household_ids) -> dict:
    """The most recent qualifying activity per household.

    *Active* is any `ProductEvent`, `ChatMessage` or `Entry` belonging to the
    household — see ``product-metrics.md``. Three queries rather than three
    per household: the caller passes a whole cohort.
    """
    from assistant.models import ChatMessage
    from finances.models import Entry

    ids = list(household_ids)
    latest: dict = {}

    for model in (ProductEvent, ChatMessage, Entry):
        rows = (
            model.objects.filter(household_id__in=ids)
            .values("household_id")
            .annotate(last=Max("created_at"))
        )
        for row in rows:
            when = row["last"]
            if when is None:
                continue
            current = latest.get(row["household_id"])
            if current is None or when > current:
                latest[row["household_id"]] = when
    return latest


def rolling_retention(cohort_ids, day: int, *, now=None) -> float | None:
    """Fraction of the cohort active on day ``day`` after signup **or later**.

    Returns ``None`` — never ``0.0`` — when no household in the cohort is old
    enough to have failed yet. A cohort that signed up yesterday has not lost
    its D7 users; it has not had the chance, and reporting it as zero is how a
    growing beta reports collapsing retention.

    Rolling, not exact-day: a household that comes back on day 9 counts for D7.
    Exact-day retention is noise at beta sample sizes — one household's Tuesday
    decides the number — and this is the question the operator actually has.
    """
    now = now or timezone.now()
    ids = list(cohort_ids)
    if not ids:
        return None

    signups = signup_times(ids)
    threshold = timedelta(days=day)
    mature = [hh for hh in ids if hh in signups and now - signups[hh] >= threshold]
    if not mature:
        return None

    latest = last_activity(mature)
    retained = sum(1 for hh in mature if hh in latest and latest[hh] - signups[hh] >= threshold)
    return retained / len(mature)


def wedge_ratio(since=None) -> tuple[int, int]:
    """``(ai_captured, manually_typed)`` — the number S14-3 calls the most
    important in the product.

    If people are typing entries rather than photographing receipts, the wedge
    is not landing. ``import`` is counted in neither half; see the module note.
    """
    qs = ProductEvent.objects.filter(name=EventName.ENTRY_CREATED)
    if since is not None:
        qs = qs.filter(created_at__gte=since)
    totals = qs.aggregate(
        ai=Count("id", filter=Q(metadata__source__in=list(AI_SOURCES))),
        manual=Count("id", filter=Q(metadata__source__in=list(MANUAL_SOURCES))),
    )
    return totals["ai"] or 0, totals["manual"] or 0


def funnel_counts(since=None) -> list[tuple[str, int]]:
    """One row per funnel step, in order, so drop-off is adjacent subtraction.

    Counts **distinct households**, not rows: `onboarding_step` and
    `receipt_photo` repeat by design, and a funnel that let one enthusiastic
    household outnumber the step above it would read as negative drop-off.
    """
    qs = ProductEvent.objects.filter(name__in=[str(name) for name in FUNNEL_ORDER])
    if since is not None:
        qs = qs.filter(created_at__gte=since)
    counted = {
        row["name"]: row["households"]
        for row in qs.values("name").annotate(households=Count("household_id", distinct=True))
    }
    return [(str(name), counted.get(str(name), 0)) for name in FUNNEL_ORDER]


def cost_per_household(since=None) -> dict:
    """Total priced USD spend per household.

    ``UsageRecord.cost_usd`` is nullable and means "not priceable", never
    "free" — so unpriced calls are left out of the sum rather than added as
    zero, exactly as `usage_report` does. A cost that quietly reads low is
    worse than one that reads "unknown".
    """
    from assistant.models import UsageRecord

    qs = UsageRecord.objects.filter(cost_usd__isnull=False)
    if since is not None:
        qs = qs.filter(created_at__gte=since)
    return {
        row["household_id"]: row["total"] or Decimal("0")
        for row in qs.values("household_id").annotate(total=Sum("cost_usd"))
    }


def assistant_turns(household_ids=None, since=None) -> dict:
    """Assistant turns per household — the engagement half of S14-4's pairing.

    A "turn" is a user message: the household said something to the product.
    Counting assistant replies instead would count our own verbosity.
    """
    from assistant.models import ChatMessage, MessageRole

    qs = ChatMessage.objects.filter(role=MessageRole.USER)
    if household_ids is not None:
        qs = qs.filter(household_id__in=list(household_ids))
    if since is not None:
        qs = qs.filter(created_at__gte=since)
    return {
        row["household_id"]: row["turns"]
        for row in qs.values("household_id").annotate(turns=Count("id"))
    }


def excluded_shadow_households() -> set:
    """Households auto-created for a user who then works from someone else's.

    Every signup mints a household even when the user immediately joins another
    one (`accounts/signals.py::create_household_for_new_user`, and
    `docs/architecture/activation-event.md` says so). Counting those as failed
    signups understates activation for exactly the users an invite flow brings
    in, so they leave both the numerator and the denominator.

    All four conditions must hold, or a real household gets deleted from the
    statistics:

    1. exactly one membership — a household anyone else joined is in use;
    2. that membership is OWNER — the household you were *invited* into is the
       one you are a MEMBER of, and it is not a shadow;
    3. that member also belongs to a different household — otherwise this is an
       ordinary solo household, which is this product's normal shape;
    4. no ``activated`` event — a household that reached the product's defining
       moment is real, whatever its membership shape.

    Condition 2 is not in E14's plan text, which listed only 1, 3 and 4. Those
    three alone also match the *invited* household (one membership, a member who
    is also elsewhere, not yet activated), which would have excluded the very
    household the invitee actually works in. The role is what tells the two
    apart, because the signup signal always creates its household as OWNER.

    Every report prints how many households this dropped: a report that silently
    narrows its own denominator reads as authoritative and is not.
    """
    from accounts.models import Household, Membership, Role

    activated = set(
        ProductEvent.objects.filter(name=EventName.ACTIVATED).values_list("household_id", flat=True)
    )
    candidates = (
        Household.objects.annotate(member_count=Count("memberships"))
        .filter(member_count=1)
        .prefetch_related("memberships")
    )

    shadows = set()
    for household in candidates:
        if household.id in activated:
            continue
        membership = household.memberships.all()[0]
        if membership.role != Role.OWNER:
            continue
        elsewhere = (
            Membership.objects.filter(user_id=membership.user_id)
            .exclude(household_id=household.id)
            .exists()
        )
        if elsewhere:
            shadows.add(household.id)
    return shadows
