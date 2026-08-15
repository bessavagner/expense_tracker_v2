"""Seed starter category memory rules (NF-token → category) for a user.

Receipt item names on fiscal coupons are abbreviated (e.g. ``ENERG MONSTER``,
``REFRIG LARANJA SJ 350ML``), so a category ``MemoryRule`` trigger must be a
token that literally appears in the NF name — NOT the colloquial word
("energético"), which would never substring-match. These starter rules encode
the user's stated preference "energético e refrigerante são Lanche" in
NF-matching form, so future receipts categorize them correctly on their own.

Idempotent (reuses ``create_memory_rule`` → ``update_or_create``). Rules whose
target category does not exist in the household are skipped with a warning.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.resolution import household_for_user
from assistant.agents.scope import AgentScope
from assistant.agents.tools import create_memory_rule
from assistant.starter_rules import DEFAULT_RULES
from finances.models import Category


class Command(BaseCommand):
    help = "Seed starter category memory rules (NF-token → category) for a user."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="username or email of the target user")

    def handle(self, *args, **options):
        user_model = get_user_model()
        ident = options["user"]
        user = (
            user_model.objects.filter(username=ident).first()
            or user_model.objects.filter(email=ident).first()
        )
        if user is None:
            raise CommandError(f"Usuário '{ident}' não encontrado.")

        # A rule is the household's: the categories it points at are shared, so
        # the existence check that guards it must ask the same question.
        scope = AgentScope(household=household_for_user(user), user=user)

        seeded = skipped = 0
        for trigger, category_name in DEFAULT_RULES:
            if (
                not Category.objects.for_household(scope.household)
                .filter(name=category_name)
                .exists()
            ):
                self.stdout.write(
                    self.style.WARNING(
                        f"pulado '{trigger}': categoria '{category_name}' não existe para {user}."
                    )
                )
                skipped += 1
                continue
            msg = create_memory_rule(scope, trigger, "category", category_name)
            self.stdout.write(f"  {msg}")
            seeded += 1

        self.stdout.write(
            self.style.SUCCESS(f"{seeded} regra(s) processada(s), {skipped} pulada(s) para {user}.")
        )
