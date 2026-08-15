"""Seed the starter catalogue into a household that predates automatic seeding.

Signup does this by itself (`accounts/signals.py`). This command exists for the
accounts that already existed when E11 shipped, and for a household minted by
`createsuperuser`, which never fires `user_signed_up`.
"""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Household, Membership, Role
from accounts.starter_data import seed_starter_data


class Command(BaseCommand):
    help = "Seed the starter categories, payment methods and memory rules for a household."

    def add_arguments(self, parser):
        parser.add_argument("--household", required=True, help="Household UUID")

    def handle(self, *args, **options):
        household = Household.objects.filter(pk=options["household"]).first()
        if household is None:
            raise CommandError(f"Casa '{options['household']}' não encontrada.")

        owner = (
            Membership.objects.filter(household=household, role=Role.OWNER)
            .select_related("user")
            .first()
        )
        created = seed_starter_data(household, owner.user if owner else None)
        self.stdout.write(
            self.style.SUCCESS(
                f"{household.name}: {created['categories']} categoria(s), "
                f"{created['payment_methods']} forma(s) de pagamento, "
                f"{created['rules']} regra(s)."
            )
        )
