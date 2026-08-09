"""Seed a database at product scale so query plans are meaningful.

Production today is one user with ~2,000 entries — small enough that Postgres
correctly sequential-scans everything, so measuring there proves nothing about
whether an index would be used. This builds a database where a
``filter(user, billing_month)`` returns tens of rows out of tens of thousands,
which is where the planner's choice actually becomes visible.

Destructive: it truncates the tables it fills. Never point it at production.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from assistant.models import ChatMessage, MemoryEmbedding, MessageRole
from core.models import CustomUser
from finances.models import Category, Entry, EntryType, Income, PaymentMethod

CATEGORY_NAMES = [
    "Alimentação",
    "Lanche",
    "Combustível",
    "Lazer",
    "Farmácia",
    "Álcool",
    "Casa",
    "Transporte",
    "Saúde",
    "Educação",
]
EMBEDDING_DIMENSIONS = 1536


class Command(BaseCommand):
    help = "Seed synthetic data at product scale for query-plan measurement."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=200)
        parser.add_argument("--entries-per-user", type=int, default=250)
        parser.add_argument(
            "--anchor",
            type=str,
            default="2026-08",
            help="YYYY-MM the generated window ends on. Explicit so runs are "
            "reproducible and the command never reads the wall clock.",
        )
        parser.add_argument("--seed", type=int, default=20260808)
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Required. Confirms you understand this truncates tables.",
        )

    def handle(self, *args, **options):
        if not options["yes"]:
            raise CommandError(
                "This TRUNCATES entries, incomes, chat messages and embeddings. "
                "Re-run with --yes if that is what you want."
            )
        try:
            year, month = (int(p) for p in options["anchor"].split("-"))
            anchor = date(year, month, 1)
        except (ValueError, TypeError) as exc:
            raise CommandError("--anchor must look like 2026-08") from exc

        rng = random.Random(options["seed"])  # noqa: S311 — synthetic data, not crypto
        n_users = options["users"]
        per_user = options["entries_per_user"]

        self.stdout.write("Truncating…")
        Entry.objects.all().delete()
        Income.objects.all().delete()
        ChatMessage.objects.all().delete()
        MemoryEmbedding.objects.all().delete()
        CustomUser.objects.filter(username__startswith="perf_").delete()

        for index in range(n_users):
            self._seed_user(rng, index, per_user, anchor)
            if (index + 1) % 25 == 0:
                self.stdout.write(f"  {index + 1}/{n_users} users")

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {n_users} users, {Entry.objects.count()} entries, "
                f"{Income.objects.count()} incomes, "
                f"{ChatMessage.objects.count()} chat messages, "
                f"{MemoryEmbedding.objects.count()} embeddings."
            )
        )

    @transaction.atomic
    def _seed_user(self, rng, index, per_user, anchor):
        user = CustomUser.objects.create(username=f"perf_{index:04d}")
        categories = [Category.objects.create(user=user, name=name) for name in CATEGORY_NAMES]
        pix = PaymentMethod.objects.create(user=user, name="Pix", type="pix")
        card = PaymentMethod.objects.create(
            user=user, name="Crédito", type="credit_card", closing_day=25
        )

        # 24 months of history ending at the anchor.
        entries = []
        for _ in range(per_user):
            months_back = rng.randint(0, 23)
            billing_month = _add_months(anchor, -months_back)
            entry_date = billing_month + timedelta(days=rng.randint(0, 27))
            entries.append(
                Entry(
                    user=user,
                    date=entry_date,
                    amount=Decimal(rng.randrange(500, 40000)) / 100,
                    description=f"Lançamento sintético {rng.randrange(10**6)}",
                    category=rng.choice(categories),
                    payment_method=rng.choice([pix, card]),
                    entry_type=rng.choices(
                        [EntryType.REGULAR, EntryType.INSTALLMENT, EntryType.SYSTEMIC],
                        weights=[80, 12, 8],
                    )[0],
                    billing_month=billing_month,
                    # Pre-computed and pinned: bulk_create bypasses save(), so the
                    # billing month has to be right going in.
                    billing_month_override=True,
                )
            )
        Entry.objects.bulk_create(entries, batch_size=500)

        Income.objects.bulk_create(
            [
                Income(
                    user=user,
                    name="Salário",
                    amount=Decimal("5000.00"),
                    month=_add_months(anchor, -back),
                )
                for back in range(12)
            ]
        )

        ChatMessage.objects.bulk_create(
            [
                ChatMessage(
                    user=user,
                    role=MessageRole.USER if turn % 2 == 0 else MessageRole.ASSISTANT,
                    content=f"mensagem sintética {turn}",
                )
                for turn in range(20)
            ]
        )

        MemoryEmbedding.objects.bulk_create(
            [
                MemoryEmbedding(
                    user=user,
                    text=f"regra sintética {slot}",
                    embedding=[rng.random() for _ in range(EMBEDDING_DIMENSIONS)],
                )
                for slot in range(10)
            ]
        )


def _add_months(d: date, n: int) -> date:
    total = (d.year * 12 + (d.month - 1)) + n
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)
