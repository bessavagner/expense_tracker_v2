"""Price the cached half of a prompt, per D03.

Every rate here was read off the provider's live pricing page on `CHECKED_ON`,
not recalled and not derived from the uncached rate. OpenAI happened to list
cached input at 10% of input across the gpt-5.x family on that date; that is an
observation, not a rule, so each row carries its own literal.

New rows rather than an edit of the 2026-08-14 ones: `effective_from` is how
this table keeps history, and rows predating this date deliberately keep a NULL
cached rate — `cost_usd_for` falls back to the full input rate for them, which
is exactly the (over-)estimate under which those `UsageRecord` costs were
frozen. Backfilling the old rows would make a historical re-price disagree with
what the ledger actually says.

`text-embedding-3-small` is absent on purpose: the pricing page lists no cached
rate for embeddings, and an embedding prompt is not reused across calls. It
keeps the full-price fallback, and
`test_every_configured_chat_model_has_a_cached_input_rate` excludes it because
it is a module constant, not a chat setting.

The two OpenRouter `:free` entries list no `input_cache_read` at all. Zero is
not an invention there: their `prompt` rate is itself zero, so every input
token costs nothing whether it was cached or not, and the seeded zero can
neither over- nor under-state the bill.

Sources consulted on 2026-08-15:
  * https://developers.openai.com/api/docs/pricing
  * https://openrouter.ai/api/v1/models

Reversible: the reverse deletes exactly the rows this migration inserted, and
the previous rows — with their NULL cached rate — take over again.
"""

from datetime import date

from django.db import migrations

CHECKED_ON = date(2026, 8, 15)

OPENAI = "https://developers.openai.com/api/docs/pricing"
OPENROUTER = "https://openrouter.ai/api/v1/models"

# (model_name, input_per_mtok, cached_input_per_mtok, output_per_mtok, source_url)
PRICES = [
    ("openai:gpt-5.4", "2.500000", "0.250000", "15.000000", OPENAI),
    ("openai:gpt-5.4-mini", "0.750000", "0.075000", "4.500000", OPENAI),
    ("openai:gpt-5.6-terra", "2.000000", "0.200000", "12.000000", OPENAI),
    ("openai:gpt-5.6-luna", "0.200000", "0.020000", "1.200000", OPENAI),
    ("openai:gpt-5.6-sol", "5.000000", "0.500000", "30.000000", OPENAI),
    ("openai-responses:gpt-5.6-terra", "2.000000", "0.200000", "12.000000", OPENAI),
    ("openai-responses:gpt-5.6-luna", "0.200000", "0.020000", "1.200000", OPENAI),
    ("openai-responses:gpt-5.6-sol", "5.000000", "0.500000", "30.000000", OPENAI),
    ("openrouter:qwen/qwen3.7-flash", "0.030000", "0.006000", "0.130000", OPENROUTER),
    (
        "openrouter:nvidia/nemotron-3-super-120b-a12b:free",
        "0.000000",
        "0.000000",
        "0.000000",
        OPENROUTER,
    ),
]


def seed(apps, schema_editor):
    ModelPrice = apps.get_model("assistant", "ModelPrice")
    for name, inp, cached, out, url in PRICES:
        ModelPrice.objects.update_or_create(
            model_name=name,
            effective_from=CHECKED_ON,
            defaults={
                "input_per_mtok": inp,
                "cached_input_per_mtok": cached,
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
    dependencies = [("assistant", "0027_usagerecord_cache_read_tokens")]
    operations = [migrations.RunPython(seed, unseed)]
