from decimal import Decimal

from django.core.management.base import BaseCommand

from core.models import CustomUser
from finances.models import Category, PaymentMethod

CATEGORIES = [
    ("Alimentação", Decimal("1300.00"), False),
    ("Lanche", Decimal("438.90"), False),
    ("Lazer", Decimal("567.87"), False),
    ("Combustível", Decimal("460.00"), False),
    ("Álcool", Decimal("511.00"), False),
    ("Higiene", Decimal("100.00"), False),
    ("Limpeza", Decimal("100.00"), False),
    ("Farmácia", Decimal("300.00"), False),
    ("Serviços", Decimal("240.00"), False),
    ("Pets", Decimal("250.00"), False),
    ("Saúde", Decimal("360.00"), False),
    ("Casa", Decimal("100.00"), False),
    ("Trabalho", Decimal("100.00"), False),
    ("Educação", Decimal("100.00"), False),
    ("Escritório", Decimal("100.00"), False),
    ("Perfumaria", Decimal("100.00"), False),
    ("Roupa", Decimal("100.00"), False),
    ("Carro", Decimal("140.00"), False),
    ("Estética", Decimal("100.00"), False),
    ("Esporte", Decimal("100.00"), False),
    ("Viagem", Decimal("100.00"), False),
    ("Transporte", Decimal("100.00"), False),
    ("Dívida", Decimal("100.00"), False),
    ("Outros", Decimal("100.00"), False),
    ("Custeio", Decimal("2000.00"), True),
    ("Financiamentos", Decimal("1000.00"), True),
]

PAYMENT_METHODS = [
    ("Dinheiro", "cash", None),
    ("Pix", "pix", None),
    ("Crédito BB - Afonso", "credit_card", 25),
    ("Crédito Santander", "credit_card", 30),
    ("Crédito Nubank", "credit_card", 30),
    ("Crédito C6", "credit_card", 25),
]


class Command(BaseCommand):
    help = "Seed initial categories and payment methods for a user"

    def add_arguments(self, parser):
        parser.add_argument("--user", type=str, required=True, help="Username to seed data for")

    def handle(self, *args, **options):
        username = options["user"]
        user = CustomUser.objects.get(username=username)
        cat_created = 0
        for name, ceiling, is_system in CATEGORIES:
            _, created = Category.objects.get_or_create(
                user=user,
                name=name,
                defaults={"budget_ceiling": ceiling, "is_system": is_system},
            )
            if created:
                cat_created += 1
        pm_created = 0
        for name, pm_type, closing_day in PAYMENT_METHODS:
            _, created = PaymentMethod.objects.get_or_create(
                user=user,
                name=name,
                defaults={"type": pm_type, "closing_day": closing_day},
            )
            if created:
                pm_created += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {cat_created} categories and {pm_created} payment methods for {username}"
            )
        )
