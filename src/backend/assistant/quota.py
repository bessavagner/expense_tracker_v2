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

    ESSENTIAL falls back to STANDARD when it is unconfigured *or* when there is
    no ``OPENROUTER_API_KEY``, so local dev and CI degrade to a working model
    rather than crash. A degrade path that itself fails is worse than no
    degrade path — and the key is the likelier of the two to be missing, since
    the model name ships with a default and the key never can.

    The key check is deliberately not "does the string start with openrouter:":
    an operator who points ESSENTIAL at some other provider gets their model,
    and it is their business to supply that provider's credentials.
    """
    if tier == Tier.ADVANCED:
        return settings.LLM_TIER_ADVANCED
    if tier == Tier.STANDARD:
        return settings.LLM_TIER_STANDARD
    essential = settings.LLM_TIER_ESSENTIAL
    if not essential:
        return settings.LLM_TIER_STANDARD
    if essential.startswith("openrouter:") and not settings.OPENROUTER_API_KEY:
        return settings.LLM_TIER_STANDARD
    return essential


def fallback_model_for(tier: str) -> str | None:
    """The second attempt for ``tier``, or ``None`` when there is none.

    Only ESSENTIAL has one: its primary is a free model, and free endpoints
    get rate-limited and deprecated (E07 spec D3).

    Returns ``None`` when ``model_for`` has already degraded to STANDARD —
    retrying a paid OpenRouter model when the key is missing would just fail
    twice and double the latency of a turn that is already working.
    """
    if tier != Tier.ESSENTIAL:
        return None
    if model_for(tier) != settings.LLM_TIER_ESSENTIAL:
        return None
    fallback = settings.LLM_TIER_ESSENTIAL_FALLBACK
    if fallback.startswith("openrouter:") and not settings.OPENROUTER_API_KEY:
        return None
    return fallback or None


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

    The window is rolling rather than calendar-bucketed, carried over from
    E01: a calendar hour lets a caller spend the whole hourly budget at 10:59
    and the whole next one at 11:00, doubling the real ceiling at exactly the
    moment that matters.
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
