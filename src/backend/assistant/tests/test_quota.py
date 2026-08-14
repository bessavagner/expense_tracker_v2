"""The single chokepoint. Every quota decision in the product happens here.

Two refusals live in this one function and they are NOT the same thing:

  * out of credits  -> degrade a tier. The user still gets an answer.
  * over the ceiling -> 429. Nothing rescues you. This is R0's guarantee.

Every date-sensitive test freezes the clock (global constraint 10).

These are sync tests driving async functions through ``async_to_sync``, which
is the suite's convention and is load-bearing here: an ``async def`` test under
``django_db`` runs its ORM work on a different connection from the one holding
the fixture transaction, so it cannot see ``household`` or ``user`` at all.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone

from assistant.models import CreditPrice, InteractionKind, UsageInteraction
from assistant.quota import (
    balance_for,
    decide,
    fallback_model_for,
    model_for,
    open_interaction,
)
from core.tiers import Tier

pytestmark = pytest.mark.django_db

# Frozen so "N hours ago" is computed from a fixed instant rather than the real
# clock — a rolling-window test that reads the real clock is exactly the
# time-bomb this freeze exists to prevent.
FROZEN = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _frozen_clock(time_machine):
    time_machine.move_to(FROZEN, tick=False)


def _spend(household, user, *, credits, tier=Tier.ADVANCED, kind=InteractionKind.TEXT, age=None):
    """Charge ``credits`` to ``household``, backdated by ``age``.

    The row names both its actor and its tenant and keeps them distinct: the
    credit balance is the household's, the abuse ceiling counts the person
    (E04 decision 1).
    """
    stamp = timezone.now() - (age or timedelta(0))
    ev = UsageInteraction.objects.create(
        household=household, user=user, kind=kind, tier=tier, credits_charged=credits
    )
    UsageInteraction.objects.filter(pk=ev.pk).update(created_at=stamp)
    return ev


def _decide(household, user, kind=InteractionKind.TEXT):
    return async_to_sync(decide)(household, user, kind, now=FROZEN)


# --- the credit cascade -------------------------------------------------


def test_a_fresh_household_gets_its_preferred_tier(household, user):
    d = _decide(household, user)
    assert d.allowed is True
    assert d.tier == Tier.ADVANCED
    assert d.degraded is False
    assert d.message is None


def test_a_household_out_of_credits_is_degraded_not_refused(household, user, plan):
    """E07 spec D2, and the DoD box that says degraded rather than refused."""
    _spend(household, user, credits=plan.monthly_credits)
    d = _decide(household, user)
    assert d.allowed is True  # <-- NOT a refusal
    assert d.tier == Tier.ESSENTIAL
    assert d.degraded is True
    assert "Essencial" in d.message


def test_a_household_that_cannot_afford_advanced_but_can_afford_standard(household, user, plan):
    """One shared pool, spent at different rates — the cascade steps down."""
    adv = CreditPrice.objects.get(tier=Tier.ADVANCED, kind=InteractionKind.TEXT)
    std = CreditPrice.objects.get(tier=Tier.STANDARD, kind=InteractionKind.TEXT)
    assert std.credits < adv.credits  # guards the fixture, not the code
    _spend(household, user, credits=plan.monthly_credits - std.credits)
    d = _decide(household, user)
    assert d.tier == Tier.STANDARD
    assert d.degraded is True


def test_a_household_that_chose_standard_is_never_upgraded_to_advanced(household, user):
    """The chokepoint overrides downward only. Choosing to save must stick."""
    household.preferred_tier = Tier.STANDARD
    household.save()
    d = _decide(household, user)
    assert d.tier == Tier.STANDARD
    assert d.degraded is False


def test_essential_never_runs_out_of_credits(household, user, plan):
    _spend(household, user, credits=plan.monthly_credits * 10)
    d = _decide(household, user, InteractionKind.IMAGE)
    assert d.allowed is True
    assert d.tier == Tier.ESSENTIAL
    assert d.credits_cost == 0


def test_last_months_spend_does_not_count_against_this_month(household, user, plan):
    """Grants are per calendar month. Frozen clock — no time bombs."""
    _spend(household, user, credits=plan.monthly_credits, age=timedelta(days=40))
    d = _decide(household, user)
    assert d.tier == Tier.ADVANCED
    assert d.degraded is False


def test_balance_reports_grant_remaining_and_renewal(household, user, plan):
    _spend(household, user, credits=100)
    granted, remaining, renews_on = async_to_sync(balance_for)(household, now=FROZEN)
    assert granted == plan.monthly_credits
    assert remaining == plan.monthly_credits - 100
    assert renews_on == date(2026, 9, 1)


def test_a_household_with_no_plan_uses_the_default_plan(household, user, plan):
    household.plan = None
    household.save()
    granted, _, _ = async_to_sync(balance_for)(household, now=FROZEN)
    assert granted == plan.monthly_credits


def test_one_members_spend_counts_against_the_others_balance(household, user, household_mate, plan):
    """Credits are the HOUSEHOLD's pool — the opposite of the abuse ceiling,
    which is per person. Both facts have to be true at once."""
    _spend(household, user, credits=plan.monthly_credits)
    d = _decide(household, household_mate)
    assert d.tier == Tier.ESSENTIAL


def test_a_neighbours_spend_does_not_touch_this_households_balance(
    household, user, other_household, other_user, plan
):
    _spend(other_household, other_user, credits=plan.monthly_credits)
    d = _decide(household, user)
    assert d.tier == Tier.ADVANCED


def test_the_balance_never_goes_negative(household, user, plan):
    """Overspend is possible — a turn is charged before it runs — but a
    negative balance would make the cascade arithmetic lie."""
    _spend(household, user, credits=plan.monthly_credits * 3)
    _, remaining, _ = async_to_sync(balance_for)(household, now=FROZEN)
    assert remaining == 0


# --- the abuse ceiling (R0's guarantee, carried over from E01) -----------


def test_the_abuse_ceiling_refuses_outright(household, user, settings):
    """Over the ceiling is a 429. No tier rescues you — this is the R0 gate."""
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 2
    for _ in range(2):
        _spend(household, user, credits=0, tier=Tier.ESSENTIAL)
    d = _decide(household, user)
    assert d.allowed is False
    assert "hora" in d.message
    assert "mensagens" in d.message


def test_the_ceiling_applies_even_on_the_free_tier(household, user, settings, plan):
    """ESSENTIAL has no plan quota. Without this it would be unbounded spend."""
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 2
    _spend(household, user, credits=plan.monthly_credits)  # forces ESSENTIAL
    for _ in range(2):
        _spend(household, user, credits=0, tier=Tier.ESSENTIAL)
    d = _decide(household, user)
    assert d.allowed is False


def test_the_ceiling_is_per_user_not_per_household(household, user, household_mate, settings):
    """One member must not be able to lock the other out."""
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 2
    for _ in range(5):
        _spend(household, user, credits=0)
    d = _decide(household, household_mate)
    assert d.allowed is True


def test_the_ceiling_window_rolls(household, user, settings):
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 2
    for _ in range(5):
        _spend(household, user, credits=0, age=timedelta(hours=2))
    d = _decide(household, user)
    assert d.allowed is True


def test_a_turn_exactly_at_the_window_edge_still_counts(household, user, settings):
    """The boundary is inclusive: an event exactly one hour old is still "this
    hour", not a loophole that lets the count reset a moment early."""
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 1
    _spend(household, user, credits=0, age=timedelta(hours=1))
    assert _decide(household, user).allowed is False


def test_a_turn_one_second_past_the_window_edge_does_not_count(household, user, settings):
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 1
    _spend(household, user, credits=0, age=timedelta(hours=1, seconds=1))
    assert _decide(household, user).allowed is True


def test_the_daily_ceiling_blocks_even_when_the_hourly_one_is_clear(household, user, settings):
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 100
    settings.ASSISTANT_ABUSE_TEXT_PER_DAY = 6
    for _ in range(6):
        _spend(household, user, credits=0, age=timedelta(hours=5))
    d = _decide(household, user)
    assert d.allowed is False
    assert "dia" in d.message


def test_the_image_ceiling_is_separate_from_the_text_ceiling(household, user, settings):
    settings.ASSISTANT_ABUSE_IMAGE_PER_HOUR = 1
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 100
    _spend(household, user, credits=0, kind=InteractionKind.IMAGE)
    assert _decide(household, user, InteractionKind.IMAGE).allowed is False
    assert _decide(household, user, InteractionKind.TEXT).allowed is True


def test_the_image_refusal_names_photos_not_messages(household, user, settings):
    settings.ASSISTANT_ABUSE_IMAGE_PER_HOUR = 1
    _spend(household, user, credits=0, kind=InteractionKind.IMAGE)
    assert "fotos" in _decide(household, user, InteractionKind.IMAGE).message


def test_the_ceiling_reads_current_settings(household, user, settings):
    """Rules are read per call, so an env change lands on the next deploy
    without a code change — and the `settings` fixture works at all."""
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 1
    _spend(household, user, credits=0)
    assert _decide(household, user).allowed is False
    settings.ASSISTANT_ABUSE_TEXT_PER_HOUR = 50
    assert _decide(household, user).allowed is True


# --- opening the interaction --------------------------------------------


def test_open_interaction_freezes_the_tier_and_the_credit_cost(household, user):
    d = _decide(household, user)
    ev = async_to_sync(open_interaction)(d, household, user, InteractionKind.TEXT)
    assert ev.tier == d.tier
    assert ev.credits_charged == d.credits_cost
    assert ev.household == household
    assert ev.user == user


def test_retuning_credit_prices_does_not_rewrite_what_was_already_spent(household, user):
    """`credits_charged` is frozen at write time. This is why the balance can
    be derived without the past shifting under it."""
    d = _decide(household, user)
    ev = async_to_sync(open_interaction)(d, household, user, InteractionKind.TEXT)
    charged = ev.credits_charged

    CreditPrice.objects.filter(tier=Tier.ADVANCED, kind=InteractionKind.TEXT).update(credits=999)
    ev.refresh_from_db()
    assert ev.credits_charged == charged


def test_an_opened_interaction_is_immediately_visible_to_the_balance(household, user, plan):
    d = _decide(household, user)
    async_to_sync(open_interaction)(d, household, user, InteractionKind.TEXT)
    _, remaining, _ = async_to_sync(balance_for)(household, now=FROZEN)
    assert remaining == plan.monthly_credits - d.credits_cost


# --- model resolution ----------------------------------------------------


def test_each_tier_resolves_to_its_configured_model(settings):
    settings.LLM_TIER_ADVANCED = "openai:big"
    settings.LLM_TIER_STANDARD = "openai:mid"
    settings.LLM_TIER_ESSENTIAL = "openrouter:free"
    settings.OPENROUTER_API_KEY = "sk-test"  # noqa: S105 — not a real credential
    assert model_for(Tier.ADVANCED) == "openai:big"
    assert model_for(Tier.STANDARD) == "openai:mid"
    assert model_for(Tier.ESSENTIAL) == "openrouter:free"


def test_essential_falls_back_to_standard_when_unconfigured(settings):
    settings.LLM_TIER_ESSENTIAL = ""
    assert model_for(Tier.ESSENTIAL) == settings.LLM_TIER_STANDARD


def test_essential_falls_back_to_standard_without_an_openrouter_key(settings):
    """CI and a fresh clone have no OPENROUTER_API_KEY. A degrade path that
    itself crashes is worse than no degrade path."""
    settings.LLM_TIER_ESSENTIAL = "openrouter:some/model:free"
    settings.OPENROUTER_API_KEY = ""
    assert model_for(Tier.ESSENTIAL) == settings.LLM_TIER_STANDARD


def test_a_non_openrouter_essential_is_not_gated_on_the_openrouter_key(settings):
    """An operator pointing ESSENTIAL somewhere else supplies that provider's
    credentials themselves; we must not second-guess them."""
    settings.LLM_TIER_ESSENTIAL = "openai:gpt-5.4-nano"
    settings.OPENROUTER_API_KEY = ""
    assert model_for(Tier.ESSENTIAL) == "openai:gpt-5.4-nano"


def test_only_essential_has_a_fallback_model(settings):
    settings.OPENROUTER_API_KEY = "sk-test"  # noqa: S105 — not a real credential
    assert fallback_model_for(Tier.ADVANCED) is None
    assert fallback_model_for(Tier.STANDARD) is None
    assert fallback_model_for(Tier.ESSENTIAL) == settings.LLM_TIER_ESSENTIAL_FALLBACK


def test_there_is_no_fallback_when_essential_already_degraded_to_standard(settings):
    """Retrying a paid OpenRouter model with no key fails twice and doubles the
    latency of a turn that is already working."""
    settings.OPENROUTER_API_KEY = ""
    assert fallback_model_for(Tier.ESSENTIAL) is None


# --- the DoD's grep ------------------------------------------------------


def test_there_is_exactly_one_enforcement_path():
    """The DoD's grep, as a test so it cannot rot.

    `assistant/throttling.py` is deleted, not deprecated. If this fails,
    someone has added a second place that decides whether a model may be
    called — which is the exact bug S07-3 exists to prevent.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    assert not (root / "assistant" / "throttling.py").exists()

    # The DoD words this as a grep; it is a Python scan so it needs no
    # subprocess and runs the same on any machine. The literal grep is run by
    # hand once at final verification, as the plan asks.
    #
    # `tests/` is skipped because this file names both symbols itself, so the
    # scan would always trip over its own source. That costs nothing: a test
    # still importing `assistant.throttling` would fail on the missing module
    # long before reaching this assertion.
    symbols = ("exceeded_rule", "throttle_denial")
    hits = [
        f"{path.relative_to(root)}:{n}"
        for path in root.rglob("*.py")
        if "tests" not in path.parts
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if any(s in line for s in symbols)
    ]
    assert not hits, "E01's throttle survives somewhere:\n  " + "\n  ".join(hits)


# --- the credit price grid (E07 Task 5) ---------------------------------


def test_essential_costs_zero_credits_for_every_kind():
    """E07 spec D2: ESSENTIAL is the free floor. Charging for it defeats it."""
    for kind in InteractionKind.values:
        assert CreditPrice.objects.get(tier=Tier.ESSENTIAL, kind=kind).credits == 0


def test_an_image_costs_more_credits_than_text_in_every_paid_tier():
    """A vision call is genuinely more expensive. The currency must say so."""
    for tier in (Tier.ADVANCED, Tier.STANDARD):
        text = CreditPrice.objects.get(tier=tier, kind=InteractionKind.TEXT).credits
        image = CreditPrice.objects.get(tier=tier, kind=InteractionKind.IMAGE).credits
        assert image > text


def test_advanced_costs_more_credits_than_standard():
    adv = CreditPrice.objects.get(tier=Tier.ADVANCED, kind=InteractionKind.TEXT).credits
    std = CreditPrice.objects.get(tier=Tier.STANDARD, kind=InteractionKind.TEXT).credits
    assert adv > std


def test_every_tier_and_kind_combination_is_priced():
    """A missing row makes `_decide_sync` fall back to zero credits, which
    would silently make a paid tier free."""
    for tier in Tier.values:
        for kind in InteractionKind.values:
            assert CreditPrice.objects.filter(tier=tier, kind=kind).exists(), f"{tier}/{kind}"
