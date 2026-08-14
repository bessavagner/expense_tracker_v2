"""Replace the placeholder credit grant with a number from real usage.

E07 spec D5. Measured on 2026-08-14 against the dev copy of the production
database, over the only window it holds real single-user traffic —
2026-06-11..2026-06-23, 5 active days out of 13:

    text turns/day  : 3, 0, 3, 2, 1   (peak 3)
    image turns/day : 0, 3, 2, 0, 0   (peak 3)

Two figures fall out of that, and they are an order of magnitude apart:

  * Actual rate. 9 text + 5 image turns in 13 days, scaled to 30 days at the
    seeded ADVANCED grid (text=3, image=12) -> ~200 credits/month.
  * Pathological peak. Every day as busy as the busiest observed day:
    (3*30)*3 + (3*30)*12 = 1350 credits/month.

Grant set to 3000 — about 15x the actual rate and 2.2x the pathological peak,
which is E01's precedent that a beta ceiling real use never touches is the
whole point. It is also the ceiling on what one household can cost us: 3000
credits buys at most 1000 ADVANCED text turns or 250 image turns a month, so
worst-case exposure per household stays in the tens of dollars rather than
being open-ended.

Caveat worth keeping: 5 active days of ONE user is thin evidence, and the
ledger this epic builds is what replaces it. Re-derive from `usage_report`
once there are households with more than one member — the credits are a
household-wide pool, and nothing here has measured two people sharing one.

`UsageInteraction.credits_charged` is frozen at write time, so changing the
grant never rewrites what anyone has already spent.
"""

from django.db import migrations

NEW = 3000
OLD = 5000  # the placeholder seeded by 0006_seed_beta_plan


def up(apps, schema_editor):
    apps.get_model("accounts", "Plan").objects.filter(slug="beta").update(monthly_credits=NEW)


def down(apps, schema_editor):
    apps.get_model("accounts", "Plan").objects.filter(slug="beta").update(monthly_credits=OLD)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0006_seed_beta_plan")]
    operations = [migrations.RunPython(up, down)]
