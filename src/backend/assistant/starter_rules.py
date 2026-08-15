"""The starter NF-token → category rules, in one place.

Receipt item names on fiscal coupons are abbreviated (``ENERG MONSTER``,
``REFRIG LARANJA SJ 350ML``), so a trigger must be a token that literally
appears in the NF name — not the colloquial word ("energético"), which would
never substring-match.

Lifted out of ``assistant/management/commands/seed_category_rules.py`` because
E11 seeds the same rules from ``accounts.starter_data`` on signup, and two
copies of this list would drift the day someone edits one. The command still
exists for an existing household that predates the automatic seeding.
"""

#: (NF-token trigger, category name). Triggers are lowercased by
#: ``create_memory_rule`` and matched case-insensitively as substrings of the
#: item description. Every category named here MUST be in
#: ``accounts.starter_data.STARTER_CATEGORIES`` — a test asserts it.
DEFAULT_RULES = [
    ("energ", "Lanche"),  # ENERG MONSTER, ENERGY MONSTER
    ("refrig", "Lanche"),  # REFRIG LARANJA ...
    ("monster", "Lanche"),  # energético (marca) — reforça "energ"
]
