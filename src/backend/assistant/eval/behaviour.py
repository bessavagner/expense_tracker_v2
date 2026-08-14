"""Behavioural cases: the judgments a cheaper model will get wrong first.

Extraction is a vision problem. Resolving a category from a loose phrase,
picking the payment method, computing a credit card's billing month, splitting a
receipt on request and refusing to double-register — those are judgment, and
judgment is what degrades when you downgrade.

Every case asserts the RESULTING LEDGER, never the wording of the reply. There
is deliberately no LLM-as-judge (epic open question 4): a judge model adds cost,
variance, and a second thing to trust.

Plan decision D-B: each case declares its own categories and payment methods and
the harness seeds exactly those. No MemoryRule is ever seeded — a score that
moves when the operator's personal rules change is not a baseline.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from assistant.eval.dataset import PaymentMethodSpec


@dataclass(frozen=True)
class ExpectedEntry:
    """One ledger row a correct run must produce.

    ``amount=None`` means "any amount strictly greater than zero" — used where
    the exact figure comes from discount proration and pinning it would test
    ``_prorate_discount``'s rounding rather than the model's judgment.
    """

    category: str
    amount: Decimal | None = None
    billing_month: date | None = None
    payment_method: str | None = None
    description_contains: str | None = None


@dataclass(frozen=True)
class World:
    """What exists before the turn runs."""

    categories: tuple[str, ...]
    payment_methods: tuple[PaymentMethodSpec, ...]
    # Payload for a PENDING ReceiptDraft, shaped exactly like
    # `ReceiptExtraction.model_dump(mode="json")` — the same thing the view writes.
    receipt_payload: dict | None = None
    # Payload for an already-REGISTERED draft, for the duplicate case.
    registered_receipt: dict | None = None
    # Entries that already exist: dicts with date/amount/description/category/
    # payment_method keys.
    existing_entries: tuple[dict, ...] = ()


@dataclass(frozen=True)
class BehaviourCase:
    """One scored conversation.

    ``opening`` decides how the FIRST prompt is built, mirroring production:
    - "text"      → `turns[0]` verbatim, as a user typing.
    - "receipt"   → `extraction_to_prompt(...)`, what the view sends after a photo.
    - "duplicate" → `build_duplicate_receipt_directive(...)`, the re-sent-photo path.
    """

    id: str
    why: str
    world: World
    opening: Literal["text", "receipt", "duplicate"]
    turns: tuple[str, ...]
    today: date
    expected_entries: tuple[ExpectedEntry, ...] = ()
    expected_total: Decimal | None = None
    expect_no_new_entries: bool = False


@dataclass(frozen=True)
class LedgerRow:
    """An `Entry` flattened to the fields a case can assert."""

    category: str
    amount: Decimal
    billing_month: date
    payment_method: str
    description: str


@dataclass(frozen=True)
class BehaviourScore:
    case_id: str
    matched: int
    expected: int
    extra: int
    total_ok: bool
    errors: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.errors

    @property
    def score(self) -> float:
        """1.0 or 0.0.

        A ledger is right or it is wrong; there is no partial credit for
        creating half of someone's expenses.
        """
        return 1.0 if self.passed else 0.0


def _matches(exp: ExpectedEntry, row: LedgerRow) -> str | None:
    """``None`` when the row satisfies the expectation, else why it does not."""
    if row.category.strip().lower() != exp.category.strip().lower():
        return f"category {row.category!r} != {exp.category!r}"
    if exp.amount is None:
        if row.amount <= 0:
            return f"{exp.category}: expected a positive amount, got {row.amount}"
    elif row.amount != exp.amount:
        return f"{exp.category}: expected {exp.amount}, got {row.amount}"
    if exp.billing_month and row.billing_month != exp.billing_month:
        return f"{exp.category}: billing_month {row.billing_month} != {exp.billing_month}"
    if exp.payment_method and row.payment_method.strip().lower() != (
        exp.payment_method.strip().lower()
    ):
        return f"{exp.category}: payment_method {row.payment_method!r} != {exp.payment_method!r}"
    if exp.description_contains and exp.description_contains.lower() not in (
        row.description.lower()
    ):
        return f"{exp.category}: description {row.description!r} lacks {exp.description_contains!r}"
    return None


def score_ledger(case: BehaviourCase, rows: Sequence[LedgerRow]) -> BehaviourScore:
    """Compare the rows the run created against what the case expects."""
    errors: list[str] = []

    if case.expect_no_new_entries:
        if rows:
            errors.append(
                f"expected NO new entries, got {len(rows)}: "
                + ", ".join(f"{r.category} {r.amount}" for r in rows)
            )
        return BehaviourScore(
            case_id=case.id,
            matched=0,
            expected=0,
            extra=len(rows),
            total_ok=not rows,
            errors=tuple(errors),
        )

    unclaimed = list(range(len(rows)))
    matched = 0
    for exp in case.expected_entries:
        hit = None
        misses: list[str] = []
        for idx in unclaimed:
            problem = _matches(exp, rows[idx])
            if problem is None:
                hit = idx
                break
            misses.append(problem)
        if hit is None:
            errors.append(
                f"no row satisfied {exp.category}"
                + (f" ({'; '.join(misses)})" if misses else " (no rows left)")
            )
        else:
            unclaimed.remove(hit)
            matched += 1

    if unclaimed:
        errors.append(
            "unexpected extra rows: "
            + ", ".join(f"{rows[i].category} {rows[i].amount}" for i in unclaimed)
        )

    total = sum((r.amount for r in rows), Decimal("0"))
    total_ok = case.expected_total is None or total == case.expected_total
    if not total_ok:
        errors.append(f"ledger total {total} != expected {case.expected_total}")

    return BehaviourScore(
        case_id=case.id,
        matched=matched,
        expected=len(case.expected_entries),
        extra=len(unclaimed),
        total_ok=total_ok,
        errors=tuple(errors),
    )


def load_behaviour_cases(ids: list[str] | None = None) -> list[BehaviourCase]:
    """All cases, or the ids asked for."""
    by_id = {c.id: c for c in BEHAVIOUR_CASES}
    if ids is None:
        return list(BEHAVIOUR_CASES)
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise ValueError(f"unknown behaviour case id(s): {', '.join(missing)}")
    return [by_id[i] for i in ids]


# ── The cases ───────────────────────────────────────────────────────────────
#
# Fixed catalogue shared by most cases (plan decision D-B). Closing day 25 makes
# the billing-month cases unambiguous in both directions.

CREDITO = PaymentMethodSpec(name="Credito C6", type="credit_card", closing_day=25)
PIX = PaymentMethodSpec(name="Pix", type="pix")
DINHEIRO = PaymentMethodSpec(name="Dinheiro", type="cash")
CATALOGUE = (CREDITO, PIX, DINHEIRO)

AMERICANAS_PAYLOAD = {
    "store": "americanas sa - 1063",
    "date": "2026-06-12",
    "discount": "3.99",
    "amount_paid": "42.16",
    "payment_hint": "CREDITO",
    "receipt_type": "fiscal_cupom",
    "confidence": 0.9,
    "items": [
        {"description": "SOUTIEN TOP B+ TAF21 BRANCO GG", "line_total": "9.99"},
        {"description": "BACONZITOS B&G ELMA CHIPS M", "line_total": "9.99"},
        {"description": "LAYS CLASSICA B&G ELMA CHIPS M", "line_total": "9.99"},
        {"description": "WAFER MAIS AMENDOIM 102G HERSHEYS", "line_total": "6.19"},
        {"description": "BATATA PRINGLES CREME E CEBOLA 109G", "line_total": "9.99"},
    ],
}

HIPERMACIONAL_PAYLOAD = {
    "store": "HIPERMACIONAL LTDA",
    "date": "2026-06-15",
    "discount": "0",
    "amount_paid": "376.70",
    "payment_hint": "CREDITO",
    "receipt_type": "fiscal_cupom",
    "confidence": 0.9,
    "items": [
        {"description": d, "line_total": v}
        for d, v in [
            ("MASSA RAINHA PASTEL 1kg", "9.95"),
            ("LINGUICA CHURRASCO 500G BACON", "18.95"),
            ("LINGUICA CHURRASCO 500G BIQUINHO", "18.95"),
            ("QUEIJO ISIS COAL Z LAC kg", "32.73"),
            ("FILE PEITO REGINA 1kg", "24.75"),
            ("FILEZINHO REGINA MILANESA 700G", "23.75"),
            ("BATATA EASYCHEF PRE FRITA 2kg", "24.85"),
            ("QUEIJO ITAMBE ZERO LAC 150G", "24.90"),
            ("LEITE UHT PIRACANJU 1L", "10.99"),
            ("IOG BETANIA YO BEM 170G PAPAIA", "8.30"),
            ("IOG BETANIA YO BEM 170G MORANGO", "8.30"),
            ("ALHO kg", "2.62"),
            ("CEBOLA AMARELA kg", "3.32"),
            ("EMP LEMON PEPPER kg", "4.55"),
            ("EMP PAPRIC DEFUMADA kg", "2.58"),
            ("EMP GERGELIM MIX kg", "4.62"),
            ("PIMENTAO kg", "1.18"),
            ("CR LEITE PIRACANJU ZERO LACT 200G", "12.50"),
            ("OVOS CAIP TIJUCA 10UN", "9.95"),
            ("BATAT PALH ELMA CHIPS 190G", "22.99"),
            ("BISC TODDY WAFER 94G CHOC", "3.15"),
            ("ENERG EXTR POWER 473ML MANGO", "14.50"),
            ("RACAO CHAMP ADULTO 85G FRANGO", "9.45"),
            ("RACAO CHAMP ADULTO 85G CARNE", "9.45"),
            ("TOALHA PAPEL C 2 SCALA", "5.49"),
            ("AMAC DOWNY 1L BRISA", "29.99"),
            ("DESOD MONANGE AERO 150ML", "9.95"),
            ("ESPUMA GILLETTE 155ML", "23.99"),
        ]
    ],
}

BEHAVIOUR_CASES: tuple[BehaviourCase, ...] = (
    BehaviourCase(
        id="americanas-split-on-request",
        why=(
            "The transcript in docs/.ai/prompts/006_ENHANCE_IMAGES_READING/contexts/"
            "iteraction.txt: asked to split, the agent registered Roupa R$42,16 and "
            "Lanche R$0,00. The split is the whole point of per-item extraction."
        ),
        world=World(
            categories=("Roupa", "Lanche", "Alimentacao"),
            payment_methods=CATALOGUE,
            receipt_payload=AMERICANAS_PAYLOAD,
        ),
        opening="receipt",
        turns=(
            "Nao, separe as categorias. O soutien e Roupa; os salgadinhos, "
            "bolacha e batata sao Lanche. A loja e Lojas Americanas e paguei "
            "no Credito C6.",
            "Confirma, pode registrar.",
        ),
        today=date(2026, 6, 20),
        # 9.13 / 33.03: the discount is re-derived as sum(lines) - amount_paid
        # = 3.99 and prorated with the residue absorbed by the largest category.
        expected_entries=(
            ExpectedEntry(
                category="Roupa",
                amount=Decimal("9.13"),
                payment_method="Credito C6",
                description_contains="Americanas",
            ),
            ExpectedEntry(
                category="Lanche",
                amount=Decimal("33.03"),
                payment_method="Credito C6",
            ),
        ),
        expected_total=Decimal("42.16"),
    ),
    BehaviourCase(
        id="hipermacional-six-categories-no-double-count",
        why=(
            "The real bug: Pets was counted twice (on its own line AND inside "
            "Alimentacao) and Lanche was merged away, turning R$376,70 into "
            "R$395,60. Six categories is where a weaker model starts merging."
        ),
        world=World(
            categories=(
                "Alimentacao",
                "Lanche",
                "Pets",
                "Casa",
                "Limpeza",
                "Perfumaria",
            ),
            payment_methods=CATALOGUE,
            receipt_payload=HIPERMACIONAL_PAYLOAD,
        ),
        opening="receipt",
        turns=("Paguei no Credito C6. Confirma, pode registrar.",),
        today=date(2026, 6, 20),
        expected_entries=(
            ExpectedEntry(category="Alimentacao", amount=Decimal("273.88")),
            ExpectedEntry(category="Lanche", amount=Decimal("14.50")),
            ExpectedEntry(category="Pets", amount=Decimal("18.90")),
            ExpectedEntry(category="Casa", amount=Decimal("5.49")),
            ExpectedEntry(category="Limpeza", amount=Decimal("29.99")),
            ExpectedEntry(category="Perfumaria", amount=Decimal("33.94")),
        ),
        expected_total=Decimal("376.70"),
    ),
    BehaviourCase(
        id="billing-month-after-closing-day",
        why=(
            "A credit purchase AFTER the closing day lands two months out, not "
            "one. Getting this wrong puts the expense on the wrong invoice and "
            "silently breaks every monthly total the dashboard shows."
        ),
        world=World(categories=("Alimentacao", "Lanche"), payment_methods=CATALOGUE),
        opening="text",
        turns=("Gastei 120 reais no supermercado hoje, no Credito C6.",),
        # Closing day 25; purchase on the 26th closes in July and is paid in August.
        today=date(2026, 6, 26),
        expected_entries=(
            ExpectedEntry(
                category="Alimentacao",
                amount=Decimal("120.00"),
                billing_month=date(2026, 8, 1),
                payment_method="Credito C6",
            ),
        ),
        expected_total=Decimal("120.00"),
    ),
    BehaviourCase(
        id="billing-month-before-closing-day",
        why=(
            "The other side of the same rule: on/before the closing day the "
            "expense is paid the following month. A model that applies one rule "
            "everywhere passes exactly one of these two cases."
        ),
        world=World(categories=("Alimentacao", "Lanche"), payment_methods=CATALOGUE),
        opening="text",
        turns=("Gastei 80 reais no supermercado hoje, no Credito C6.",),
        today=date(2026, 6, 12),
        expected_entries=(
            ExpectedEntry(
                category="Alimentacao",
                amount=Decimal("80.00"),
                billing_month=date(2026, 7, 1),
                payment_method="Credito C6",
            ),
        ),
        expected_total=Decimal("80.00"),
    ),
    BehaviourCase(
        id="category-and-method-from-a-loose-phrase",
        why=(
            "Nothing in the sentence names a category or a payment method "
            "verbatim. Resolving 'racao do cachorro' to Pets and 'pix' to the "
            "registered Pix method is the judgment that degrades first."
        ),
        world=World(categories=("Alimentacao", "Pets", "Casa"), payment_methods=CATALOGUE),
        opening="text",
        turns=("Comprei racao pro cachorro por 45 reais no pix hoje.",),
        today=date(2026, 6, 12),
        expected_entries=(
            ExpectedEntry(
                category="Pets",
                amount=Decimal("45.00"),
                billing_month=date(2026, 6, 1),
                payment_method="Pix",
            ),
        ),
        expected_total=Decimal("45.00"),
    ),
    BehaviourCase(
        id="refuses-to-double-register-a-known-receipt",
        why=(
            "The PAGUE MENOS incident: a photo re-sent to fix the date opened a "
            "second commit flow and the following 'sim' registered the receipt "
            "twice. The ledger must not grow."
        ),
        world=World(
            categories=("Alimentacao", "Lanche"),
            payment_methods=CATALOGUE,
            registered_receipt=HIPERMACIONAL_PAYLOAD,
            existing_entries=(
                {
                    "date": "2026-06-15",
                    "amount": "376.70",
                    "description": "HIPERMACIONAL LTDA - mercearia",
                    "category": "Alimentacao",
                    "payment_method": "Credito C6",
                },
            ),
        ),
        opening="duplicate",
        turns=("Sim.", "Isso mesmo, pode confirmar."),
        today=date(2026, 6, 16),
        expect_no_new_entries=True,
    ),
    BehaviourCase(
        id="refuses-to-invent-an-unreadable-amount",
        why=(
            "When amount_paid is not legible the agent must ASK, never guess. A "
            "guessed total is a wrong expense that looks completely normal in "
            "the ledger and is never noticed."
        ),
        world=World(
            categories=("Alimentacao", "Lanche"),
            payment_methods=CATALOGUE,
            receipt_payload={
                "store": "MERCADINHO SAO JOSE",
                "date": "2026-06-18",
                "discount": None,
                "amount_paid": None,
                "payment_hint": None,
                "receipt_type": "fiscal_cupom",
                "confidence": 0.35,
                "items": [
                    {"description": "ARROZ 5KG", "line_total": "24.90"},
                    {"description": "FEIJAO 1KG", "line_total": "8.50"},
                ],
            },
        ),
        opening="receipt",
        turns=("Nao consigo ler o total, esta borrado.",),
        today=date(2026, 6, 20),
        expect_no_new_entries=True,
    ),
)
