"""Price the gpt-5.6 family, now that it is the production default.

`LLM_ASSISTANT_MODEL`, `LLM_VISION_MODEL` and `LLM_MODEL` moved from
`openai:gpt-5.4` to `openai:gpt-5.6-terra`. Without a row here `price_for`
returns None for every call the product makes, and the operator cost report
silently reads zero — which is worse than reporting nothing, because a zero
looks like an answer.

E07 spec D3: read off the provider's live pricing page on `CHECKED_ON`, not
recalled. gpt-5.6-terra is both a newer generation and cheaper than the gpt-5.4
it replaces — $2.00/$12.00 per Mtok against $2.50/$15.00.

The gpt-5.4 rows from migration 0019 stay: `effective_from` keeps history, and
`UsageRecord` rows written while gpt-5.4 was the default must still price
correctly when a backfill re-reads them.

Sources consulted on 2026-08-14:
  * https://developers.openai.com/api/docs/pricing

Reversible: the reverse deletes exactly the rows this migration inserted.
"""

from datetime import date

from django.db import migrations

CHECKED_ON = date(2026, 8, 14)

OPENAI = "https://developers.openai.com/api/docs/pricing"

# (model_name, input_per_mtok, output_per_mtok, source_url)
#
# `model_name` must match the settings value byte for byte, provider prefix
# included — `price_for` looks up by exact string, and a near-miss meters at
# None forever.
PRICES = [
    # The new LLM_MODEL / LLM_ASSISTANT_MODEL / LLM_VISION_MODEL, and with them
    # LLM_TIER_ADVANCED and LLM_TIER_STANDARD, which derive from the assistant
    # model until E09 splits them.
    ("openai:gpt-5.6-terra", "2.000000", "12.000000", OPENAI),
    # Priced ahead of use, not because anything points here today: the two
    # siblings bracket terra on cost, so they are the obvious candidates the
    # E08 harness will be pointed at. An unpriced challenger reports a blank
    # USD column, which reads as "free" to a tired operator.
    ("openai:gpt-5.6-sol", "5.000000", "30.000000", OPENAI),
    ("openai:gpt-5.6-luna", "0.200000", "1.200000", OPENAI),
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
    dependencies = [("assistant", "0022_seed_credit_prices")]
    operations = [migrations.RunPython(seed, unseed)]
