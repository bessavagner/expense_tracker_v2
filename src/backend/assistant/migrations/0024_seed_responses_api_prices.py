"""Price the gpt-5.6 family again under its `openai-responses:` model strings.

`price_for` matches `model_name` **byte for byte** (`assistant/pricing.py`), and
pydantic-ai routes `openai:` to /v1/chat/completions but `openai-responses:` to
/v1/responses. Same model, same published price, different string — so without
these rows a Responses-API run reports **zero USD**, which reads as "free"
rather than "unmeasured".

Why the second surface exists at all: OpenAI rejects function tools alongside
`reasoning_effort` on /v1/chat/completions for the gpt-5.6 family, and every one
of our agents uses function tools (`output_type=` compiles to one). The two ways
out are to turn reasoning off on the chat surface, or to keep it on and move to
/v1/responses. E08 measures both before E09 picks — see
`assistant/agents/model_compat.py`.

Prices are unchanged from migration 0023 and re-read from the same live page on
CHECKED_ON, not copied across on the assumption that a surface cannot be priced
differently.

Sources consulted on 2026-08-14:
  * https://developers.openai.com/api/docs/pricing

Reversible: the reverse deletes exactly the rows this migration inserted. If
E09 settles on the chat surface, this migration can be rolled back and the rows
disappear without touching the `openai:` ones history depends on.
"""

from datetime import date

from django.db import migrations

CHECKED_ON = date(2026, 8, 14)

OPENAI = "https://developers.openai.com/api/docs/pricing"

# (model_name, input_per_mtok, output_per_mtok, source_url)
PRICES = [
    ("openai-responses:gpt-5.6-terra", "2.000000", "12.000000", OPENAI),
    ("openai-responses:gpt-5.6-luna", "0.200000", "1.200000", OPENAI),
    ("openai-responses:gpt-5.6-sol", "5.000000", "30.000000", OPENAI),
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
    dependencies = [("assistant", "0023_seed_gpt_5_6_prices")]
    operations = [migrations.RunPython(seed, unseed)]
