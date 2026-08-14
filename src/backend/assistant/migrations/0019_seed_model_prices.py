"""Seed the price table from prices checked on the date below.

Reversible: the reverse deletes exactly the rows this migration inserted, so
`migrate assistant 0018` is clean.

E07 spec D3: these numbers were read off the provider's live pricing pages on
`CHECKED_ON`, not recalled. If you are editing this file, re-read the pages.

Sources consulted on 2026-08-14:
  * https://developers.openai.com/api/docs/pricing
  * https://openrouter.ai/api/v1/models  (the catalogue endpoint behind
    openrouter.ai/models; it reports price per token, converted to per-Mtok
    here)

Transcription models are deliberately absent — providers price transcription
per MINUTE of audio and this table models tokens only. That gap is asserted by
`test_pricing_gaps_are_declared` and documented in the runbook, so it stays a
decision rather than an oversight.
"""

from datetime import date

from django.db import migrations

CHECKED_ON = date(2026, 8, 14)

OPENAI = "https://developers.openai.com/api/docs/pricing"
OPENROUTER = "https://openrouter.ai/api/v1/models"

# (model_name, input_per_mtok, output_per_mtok, source_url)
#
# `model_name` must match the settings value byte for byte, provider prefix
# included — `price_for` looks up by exact string, and a near-miss meters at
# None forever.
PRICES = [
    # LLM_ASSISTANT_MODEL, LLM_VISION_MODEL, and (until E09 splits them)
    # LLM_TIER_ADVANCED and LLM_TIER_STANDARD all resolve to this one.
    ("openai:gpt-5.4", "2.500000", "15.000000", OPENAI),
    # LLM_MODEL. The settings default is gpt-5.4, but deployments override it —
    # the dev .env points at mini — and an override that outruns this table
    # meters at None forever. Standard tier, not batch/flex/fast: the assistant
    # calls the synchronous API.
    ("openai:gpt-5.4-mini", "0.750000", "4.500000", OPENAI),
    # EMBEDDING_MODEL — a module constant in services/embedding.py, not a
    # setting, but Task 9 meters it so it needs a price like anything else.
    # Embeddings have no output tokens; zero here is a fact, not a gap.
    ("text-embedding-3-small", "0.020000", "0.000000", OPENAI),
    # LLM_TIER_ESSENTIAL — free, and priced at 0/0 explicitly so that "free" is
    # a recorded fact rather than a missing row indistinguishable from an
    # oversight. Chosen for tool support: the assistant is tool-heavy, and a
    # free model that cannot call tools is broken rather than cheap.
    ("openrouter:nvidia/nemotron-3-super-120b-a12b:free", "0.000000", "0.000000", OPENROUTER),
    # LLM_TIER_ESSENTIAL_FALLBACK — free endpoints get rate-limited and
    # retired, so the degrade path needs a paid floor. ~1/80th of gpt-5.4 on
    # input and ~1/115th on output.
    ("openrouter:qwen/qwen3.7-flash", "0.030000", "0.130000", OPENROUTER),
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
    dependencies = [("assistant", "0018_model_price")]
    operations = [migrations.RunPython(seed, unseed)]
