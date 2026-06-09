"""Batch-import financial data from a directory of CSV files.

Recognised files (by name) inside ``--dir``:

* ``formas_pagamento.csv`` — payment methods (wide: one closing-day column per month)
* ``renda.csv``            — incomes (wide: one amount column per month)
* ``sistemicas.csv``       — systemic expenses (wide, with a ``categoria`` column)
* ``parcelamentos.csv``    — installment plans
* any other ``*.csv``      — regular monthly entries (``data,valor,descrição,categoria,forma``)

The command is idempotent: re-running it does not create duplicates.
"""

import csv
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import CustomUser
from finances.models import (
    Category,
    Entry,
    EntryType,
    Income,
    InstallmentPlan,
    PaymentMethod,
    PaymentMethodClosingDay,
    PaymentType,
    SystemicExpense,
)
from finances.services.csv_parser import parse_amount, parse_date, parse_wide_csv

SPECIAL_FILES = {
    "formas_pagamento.csv",
    "renda.csv",
    "sistemicas.csv",
    "parcelamentos.csv",
}


class Command(BaseCommand):
    help = "Import financial data (entries, incomes, systemics, installments) from CSV files."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Username to import data for")
        parser.add_argument("--dir", required=True, help="Directory containing the CSV files")

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            self.user = CustomUser.objects.get(username=options["user"])
        except CustomUser.DoesNotExist as e:
            raise CommandError(f"User '{options['user']}' does not exist.") from e

        self.base = Path(options["dir"])
        if not self.base.is_dir():
            raise CommandError(f"Directory '{self.base}' does not exist.")

        self._cat_cache: dict[str, Category] = {
            c.name.lower(): c for c in Category.objects.filter(user=self.user)
        }
        self._pm_cache: dict[str, PaymentMethod] = {
            p.name.lower(): p for p in PaymentMethod.objects.filter(user=self.user)
        }

        # Order matters: payment methods and categories must exist before entries.
        self._import_payment_methods()
        self._import_income()
        self._import_systemics()
        self._import_installments()
        self._import_regular_entries()

    # ---- helpers --------------------------------------------------------

    def _get_category(self, name: str) -> Category:
        key = name.strip().lower()
        cat = self._cat_cache.get(key)
        if cat is None:
            cat, _ = Category.objects.get_or_create(user=self.user, name=name.strip())
            self._cat_cache[key] = cat
            self.stdout.write(f"  + categoria criada: {name.strip()}")
        return cat

    def _get_payment_method(self, name: str, default_type: str = PaymentType.PIX) -> PaymentMethod:
        key = name.strip().lower()
        pm = self._pm_cache.get(key)
        if pm is None:
            pm, _ = PaymentMethod.objects.get_or_create(
                user=self.user, name=name.strip(), defaults={"type": default_type}
            )
            self._pm_cache[key] = pm
            self.stdout.write(f"  + forma de pagamento criada: {name.strip()}")
        return pm

    # ---- importers ------------------------------------------------------

    def _import_payment_methods(self):
        path = self.base / "formas_pagamento.csv"
        if not path.exists():
            return
        self.stdout.write("Importando formas de pagamento...")
        with path.open(encoding="utf-8") as f:
            rows = parse_wide_csv(f, key_fields=["nome"])

        for row in rows:
            name = row["nome"]
            # months map: first-of-month -> Decimal(closing_day) (-1 means "none")
            day_by_month = {m: int(v) for m, v in row["months"].items()}
            positive_days = [d for d in day_by_month.values() if d > 0]

            if name.lower() == "dinheiro":
                pm_type = PaymentType.CASH
            elif positive_days:
                pm_type = PaymentType.CREDIT_CARD
            else:
                pm_type = PaymentType.PIX

            default_day = Counter(positive_days).most_common(1)[0][0] if positive_days else None

            pm, _ = PaymentMethod.objects.update_or_create(
                user=self.user,
                name=name,
                defaults={"type": pm_type, "closing_day": default_day},
            )
            self._pm_cache[name.lower()] = pm

            if pm_type == PaymentType.CREDIT_CARD:
                for month, day in day_by_month.items():
                    if day > 0 and day != default_day:
                        PaymentMethodClosingDay.objects.update_or_create(
                            payment_method=pm,
                            month=month,
                            defaults={"closing_day": day},
                        )

    def _import_income(self):
        path = self.base / "renda.csv"
        if not path.exists():
            return
        self.stdout.write("Importando rendas...")
        with path.open(encoding="utf-8") as f:
            rows = parse_wide_csv(f, key_fields=["nome"])

        for row in rows:
            for month, amount in row["months"].items():
                Income.objects.update_or_create(
                    user=self.user,
                    name=row["nome"],
                    month=month,
                    defaults={"amount": amount},
                )

    def _import_systemics(self):
        path = self.base / "sistemicas.csv"
        if not path.exists():
            return
        self.stdout.write("Importando gastos sistemáticos...")
        with path.open(encoding="utf-8") as f:
            rows = parse_wide_csv(f, key_fields=["nome", "categoria"])

        pix = self._get_payment_method("Pix", default_type=PaymentType.PIX)

        for row in rows:
            months = row["months"]
            if not months:
                continue
            category = self._get_category(row["categoria"])
            default_amount = Counter(months.values()).most_common(1)[0][0]
            se, _ = SystemicExpense.objects.update_or_create(
                user=self.user,
                name=row["nome"],
                defaults={
                    "category": category,
                    "payment_method": pix,
                    "default_amount": default_amount,
                },
            )
            for month, amount in months.items():
                exists = Entry.objects.filter(
                    user=self.user, systemic_expense=se, date=month
                ).exists()
                if not exists:
                    se.create_monthly_entry(month, amount=amount, payment_method=pix)

    def _import_installments(self):
        path = self.base / "parcelamentos.csv"
        if not path.exists():
            return
        self.stdout.write("Importando parcelamentos...")
        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                if not (raw.get("descrição") or "").strip():
                    continue
                entry_date = parse_date(raw["data"])
                description = raw["descrição"].strip()
                total = parse_amount(raw["valor"])
                category = self._get_category(raw["categoria"])
                payment_method = self._get_payment_method(raw["forma"])
                if InstallmentPlan.objects.filter(
                    user=self.user,
                    date=entry_date,
                    total_amount=total,
                    description=description,
                    payment_method=payment_method,
                ).exists():
                    continue
                plan = InstallmentPlan.objects.create(
                    user=self.user,
                    date=entry_date,
                    description=description,
                    category=category,
                    payment_method=payment_method,
                    total_amount=total,
                    num_installments=int(raw["parcelas"]),
                    installment_amount=parse_amount(raw["valor_parcela"]),
                )
                plan.generate_entries()

    def _import_regular_entries(self):
        monthly = sorted(
            p for p in self.base.glob("*.csv") if p.name not in SPECIAL_FILES
        )
        for path in monthly:
            self.stdout.write(f"Importando entradas de {path.name}...")
            with path.open(encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for raw in reader:
                    if not (raw.get("descrição") or "").strip():
                        continue
                    entry_date = parse_date(raw["data"])
                    amount = parse_amount(raw["valor"])
                    description = raw["descrição"].strip()
                    category = self._get_category(raw["categoria"])
                    payment_method = self._get_payment_method(raw["forma"])
                    if Entry.objects.filter(
                        user=self.user,
                        date=entry_date,
                        amount=amount,
                        description=description,
                        category=category,
                        payment_method=payment_method,
                    ).exists():
                        continue
                    Entry.objects.create(
                        user=self.user,
                        date=entry_date,
                        amount=amount,
                        description=description,
                        category=category,
                        payment_method=payment_method,
                        entry_type=EntryType.REGULAR,
                    )
