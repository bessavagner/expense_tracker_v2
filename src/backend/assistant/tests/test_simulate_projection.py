"""The what-if simulation, at both the service and the tool layer.

The service tests came first and passed throughout E04 — which is precisely why
nobody noticed that the *tool* was passing the whole `AgentScope` where the
service had started expecting a household. A service test cannot see a broken
call site. The tool-layer test at the bottom is the one that can.
"""

import types
from datetime import date
from decimal import Decimal

import pytest
from model_bakery import baker

from finances.services.whatif import HypotheticalItem, HypoType, simulate_projection_summary


@pytest.mark.django_db
def test_summary_reports_delta(user, household):
    baker.make(
        "finances.Income", household=household, amount=Decimal("3000"), month=date(2026, 7, 1)
    )
    items = [
        HypotheticalItem(
            id="a",
            type=HypoType.INCOME,
            label="bônus",
            amount=Decimal("1000"),
            month=date(2026, 7, 1),
        )
    ]
    out = simulate_projection_summary(
        household, items, start=date(2026, 7, 1), months=1, today=date(2026, 6, 20)
    )
    assert "1000" in out
    assert "2026-07" in out or "07/2026" in out


@pytest.mark.django_db(transaction=True)
@pytest.mark.anyio
async def test_the_tool_passes_a_household_to_the_service(user, household, scope):
    """The tool must unwrap `ctx.deps.household`, not hand over the scope.

    `for_household` only short-circuits on None, so an `AgentScope` falls
    through to `filter(household=<AgentScope>)` and raises on UUID validation —
    it fails closed rather than leaking, but the tool errors on every call.
    Passing the scope here reproduces that; passing the household does not.
    """
    from asgiref.sync import sync_to_async

    from assistant.agents.assistant import simulate_projection

    await sync_to_async(baker.make)(
        "finances.Income", household=household, amount=Decimal("3000"), month=date(2026, 7, 1)
    )
    items = [
        HypotheticalItem(
            id="a",
            type=HypoType.INCOME,
            label="bônus",
            amount=Decimal("1000"),
            month=date(2026, 7, 1),
        )
    ]

    # Only `.deps` is read by the tool body; a stand-in keeps this test from
    # breaking on pydantic_ai's RunContext constructor changing shape.
    ctx = types.SimpleNamespace(deps=scope)

    out = await simulate_projection(ctx, items, start_year=2026, start_month=7, months=1)

    assert "1000" in out
    assert "Erro" not in out, out
