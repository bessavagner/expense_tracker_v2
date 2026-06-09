"""Seed rich QA data for visual testing — entries, income, installments, systemics."""

import random
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from core.models import CustomUser
from finances.models import (
    Category,
    Entry,
    EntryType,
    Income,
    InstallmentPlan,
    PaymentMethod,
    SystemicExpense,
)

# Realistic expense descriptions per category
EXPENSE_DATA = {
    "Alimentação": [
        ("Supermercado Cosmos - compras da semana", "120.00", "250.00"),
        ("Atacadão - compras do mês", "300.00", "550.00"),
        ("Feira livre - frutas e verduras", "30.00", "80.00"),
        ("Açougue Boi Gordo", "60.00", "150.00"),
    ],
    "Lanche": [
        ("Subway - almoço", "25.00", "45.00"),
        ("McDonald's", "30.00", "60.00"),
        ("Padaria Flor de Trigo", "10.00", "30.00"),
        ("iFood - jantar", "35.00", "70.00"),
    ],
    "Combustível": [
        ("Posto Ipiranga - gasolina", "150.00", "250.00"),
        ("Posto Único - gasolina", "100.00", "200.00"),
    ],
    "Lazer": [
        ("Netflix", "39.90", "39.90"),
        ("Cinema - ingressos", "40.00", "80.00"),
        ("Spotify", "21.90", "21.90"),
    ],
    "Farmácia": [
        ("Drogasil - medicamentos", "30.00", "120.00"),
        ("Farmácia Pague Menos", "20.00", "80.00"),
    ],
    "Álcool": [
        ("Bar do Zé - cerveja", "40.00", "100.00"),
        ("Empório da Cerveja", "30.00", "80.00"),
    ],
    "Pets": [
        ("Petz - ração", "80.00", "150.00"),
        ("Veterinário - consulta", "100.00", "200.00"),
    ],
    "Higiene": [
        ("Shampoo e condicionador", "25.00", "60.00"),
        ("Produtos de higiene pessoal", "20.00", "50.00"),
    ],
    "Serviços": [
        ("Barbeiro", "35.00", "50.00"),
        ("Lavanderia", "40.00", "80.00"),
    ],
    "Saúde": [
        ("Consulta médica", "150.00", "300.00"),
    ],
    "Transporte": [
        ("Uber - corrida", "15.00", "40.00"),
        ("Estacionamento", "10.00", "25.00"),
    ],
}

SYSTEMIC_EXPENSES = [
    ("Enel - energia", "Custeio", "180.00"),
    ("Unimed - Amanda", "Saúde", "450.00"),
    ("Internet Claro", "Custeio", "120.00"),
    ("Aluguel", "Custeio", "1200.00"),
    ("Condomínio", "Custeio", "350.00"),
    ("Água SAAE", "Custeio", "80.00"),
]

INSTALLMENT_PLANS = [
    ('TV Samsung 55" Crystal UHD', "Casa", "Crédito Nubank", "3499.90", 12),
    ("iPhone 15 128GB", "Outros", "Crédito C6", "4999.00", 10),
    ("Sofá retrátil 3 lugares", "Casa", "Crédito Santander", "2800.00", 6),
]


class Command(BaseCommand):
    help = "Seed rich QA data (entries, income, installments, systemics) for a user"

    def add_arguments(self, parser):
        parser.add_argument("--user", type=str, required=True, help="Username to seed QA data for")

    def handle(self, *args, **options):
        username = options["user"]
        try:
            user = CustomUser.objects.get(username=username)
        except CustomUser.DoesNotExist as e:
            raise CommandError(f"User '{username}' does not exist.") from e

        categories = {c.name: c for c in Category.objects.filter(user=user)}
        payment_methods = {pm.name: pm for pm in PaymentMethod.objects.filter(user=user)}

        if not categories or not payment_methods:
            raise CommandError("Run seed_data first to create categories and payment methods.")

        # Determine months to seed: current month and 5 months back
        today = date.today()
        months = []
        current = date(today.year, today.month, 1)
        for _ in range(6):
            months.append(current)
            if current.month == 1:
                current = date(current.year - 1, 12, 1)
            else:
                current = date(current.year, current.month - 1, 1)
        months.reverse()  # oldest first

        # Skip if data already exists
        existing = Entry.objects.filter(user=user, entry_type=EntryType.REGULAR).count()
        if existing > 10:
            self.stdout.write(
                self.style.WARNING(f"User already has {existing} regular entries. Skipping.")
            )
            return

        random.seed(42)  # Reproducible data

        income_count = self._seed_income(user, months)
        systemic_count = self._seed_systemics(user, categories, payment_methods, months)
        entry_count = self._seed_entries(user, categories, payment_methods, months)
        installment_count = self._seed_installments(user, categories, payment_methods, months)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded for {username}: {income_count} income records, "
                f"{entry_count} regular entries, {systemic_count} systemic entries, "
                f"{installment_count} installment entries"
            )
        )

    def _seed_income(self, user, months):
        count = 0
        for month in months:
            for name, amount in [("Salário", "8000.00"), ("Bolsa PIBID", "400.00")]:
                _, created = Income.objects.get_or_create(
                    user=user,
                    name=name,
                    month=month,
                    defaults={
                        "amount": Decimal(amount),
                        "is_recurring": True,
                        "recurrence_start": months[0],
                    },
                )
                if created:
                    count += 1
        return count

    def _seed_systemics(self, user, categories, payment_methods, months):
        count = 0
        pix = payment_methods.get("Pix")
        for name, cat_name, default_amount in SYSTEMIC_EXPENSES:
            category = categories.get(cat_name)
            if not category:
                continue
            systemic, _ = SystemicExpense.objects.get_or_create(
                user=user,
                name=name,
                defaults={
                    "category": category,
                    "payment_method": pix,
                    "default_amount": Decimal(default_amount),
                },
            )
            for month in months:
                exists = Entry.objects.filter(
                    user=user, systemic_expense=systemic, billing_month=month
                ).exists()
                if not exists:
                    # Vary amount slightly for realism
                    variation = Decimal(str(random.uniform(0.9, 1.1)))
                    amount = (Decimal(default_amount) * variation).quantize(Decimal("0.01"))
                    systemic.create_monthly_entry(month, amount=amount, payment_method=pix)
                    count += 1
        return count

    def _seed_entries(self, user, categories, payment_methods, months):
        pm_list = list(payment_methods.values())
        count = 0
        for month in months:
            # 8-12 regular entries per month
            num_entries = random.randint(8, 12)
            for _ in range(num_entries):
                # Pick a random category that has expense data
                cat_name = random.choice(list(EXPENSE_DATA.keys()))
                category = categories.get(cat_name)
                if not category:
                    continue
                desc_data = random.choice(EXPENSE_DATA[cat_name])
                description = desc_data[0]
                min_amount = Decimal(desc_data[1])
                max_amount = Decimal(desc_data[2])
                amount = (
                    min_amount + (max_amount - min_amount) * Decimal(str(random.random()))
                ).quantize(Decimal("0.01"))

                # Random day in the month
                if month.month in (1, 3, 5, 7, 8, 10, 12):
                    max_day = 28  # safe for all months
                else:
                    max_day = 28
                day = random.randint(1, max_day)
                entry_date = date(month.year, month.month, day)

                pm = random.choice(pm_list)
                Entry.objects.create(
                    user=user,
                    date=entry_date,
                    amount=amount,
                    description=description,
                    category=category,
                    payment_method=pm,
                    entry_type=EntryType.REGULAR,
                )
                count += 1
        return count

    def _seed_installments(self, user, categories, payment_methods, months):
        count = 0
        # Start installments 3 months ago
        start_month = months[2] if len(months) > 2 else months[0]

        for description, cat_name, pm_name, total, num in INSTALLMENT_PLANS:
            category = categories.get(cat_name)
            pm = payment_methods.get(pm_name)
            if not category or not pm:
                continue

            exists = InstallmentPlan.objects.filter(user=user, description=description).exists()
            if exists:
                continue

            total_amount = Decimal(total)
            installment_amount = (total_amount / num).quantize(Decimal("0.01"))

            plan = InstallmentPlan.objects.create(
                user=user,
                date=start_month,
                description=description,
                category=category,
                payment_method=pm,
                total_amount=total_amount,
                num_installments=num,
                installment_amount=installment_amount,
            )
            entries = plan.generate_entries()
            count += len(entries)
        return count
