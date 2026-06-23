from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from asgiref.sync import sync_to_async as _sync_to_async
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from assistant.agents.memory import (
    AUTO_APPLY,
    CONFIRM_APPLY,
    find_matching_rules,
    find_semantic_matches,
)
from assistant.models import MemoryRule, MemorySource, ReceiptDraft, ReceiptDraftStatus
from assistant.services.embedding import get_embedding
from finances.models import (
    Category,
    Entry,
    EntryType,
    Income,
    InstallmentPlan,
    PaymentMethod,
    SystemicExpense,
)
from finances.models.payment_method import PaymentType


def list_categories(user) -> list[str]:
    """List available category names for the user."""
    return list(Category.objects.filter(user=user).order_by("name").values_list("name", flat=True))


def list_payment_methods(user) -> list[str]:
    """List available active payment method names for the user."""
    return list(
        PaymentMethod.objects.filter(user=user, is_active=True)
        .order_by("name")
        .values_list("name", flat=True)
    )


def _resolve_by_name(queryset, raw_name: str):
    """Resolve a single model instance by name, leniently.

    Tries an exact case-insensitive match first, then a unique
    case-insensitive substring match (so "c6" → "Crédito C6"). Returns a
    tuple ``(obj, matches)``: ``obj`` is the unique match or ``None``, and
    ``matches`` lists the candidate names (used to build an ambiguity message
    when more than one partial match exists).
    """
    name = (raw_name or "").strip()
    exact = queryset.filter(name__iexact=name).first()
    if exact is not None:
        return exact, [exact.name]
    partial = list(queryset.filter(name__icontains=name)) if name else []
    if len(partial) == 1:
        return partial[0], [partial[0].name]
    return None, [p.name for p in partial]


def create_entry(
    user,
    date_str: str,
    amount_str: str,
    description: str,
    category_name: str,
    payment_method_name: str,
) -> str:
    """Create an expense entry. Returns a confirmation or error message."""
    # Validate category (lenient: case-insensitive / unique partial match)
    category, cat_matches = _resolve_by_name(Category.objects.filter(user=user), category_name)
    if category is None:
        if len(cat_matches) > 1:
            return (
                f"Erro: categoria '{category_name}' é ambígua. "
                f"Você quis dizer: {', '.join(cat_matches)}?"
            )
        available = ", ".join(list_categories(user))
        return f"Erro: categoria '{category_name}' não encontrada. Disponíveis: {available}"

    # Validate payment method (lenient resolution)
    payment_method, pm_matches = _resolve_by_name(
        PaymentMethod.objects.filter(user=user, is_active=True), payment_method_name
    )
    if payment_method is None:
        if len(pm_matches) > 1:
            return (
                f"Erro: forma de pagamento '{payment_method_name}' é ambígua. "
                f"Você quis dizer: {', '.join(pm_matches)}?"
            )
        available = ", ".join(list_payment_methods(user))
        return (
            f"Erro: forma de pagamento '{payment_method_name}' não encontrada. "
            f"Disponíveis: {available}"
        )

    # Parse date
    try:
        entry_date = date.fromisoformat(date_str)
    except ValueError:
        return f"Erro: data inválida '{date_str}'. Use formato AAAA-MM-DD."

    # Parse amount
    try:
        amount = Decimal(amount_str)
    except InvalidOperation:
        return f"Erro: valor inválido '{amount_str}'."

    # Create entry
    entry = Entry.objects.create(
        user=user,
        date=entry_date,
        amount=amount,
        description=description,
        category=category,
        payment_method=payment_method,
    )

    return (
        f"Entrada criada! {entry.description} — R$ {entry.amount} "
        f"em {category.name} via {payment_method.name} "
        f"(fatura: {entry.billing_month:%m/%Y})"
    )


_CENTS = Decimal("0.01")


def _prorate_discount(
    category_sums: dict[str, Decimal], discount: Decimal
) -> dict[str, Decimal]:
    """Rateia ``discount`` entre categorias na proporção de seus subtotais.

    Arredonda cada parcela a 2 casas; o resíduo de centavos vai para a MAIOR
    categoria, de modo que ``sum(parcelas) == discount`` exatamente.
    """
    total = sum(category_sums.values(), Decimal("0"))
    if discount <= 0 or total <= 0:
        return {cat: Decimal("0.00") for cat in category_sums}

    # Maior subtotal absorve o resíduo de arredondamento.
    order = sorted(category_sums, key=lambda c: category_sums[c], reverse=True)
    largest, rest = order[0], order[1:]
    allocated: dict[str, Decimal] = {}
    acc = Decimal("0.00")
    for cat in rest:
        share = (discount * category_sums[cat] / total).quantize(
            _CENTS, rounding=ROUND_HALF_UP
        )
        allocated[cat] = share
        acc += share
    allocated[largest] = (discount - acc).quantize(_CENTS, rounding=ROUND_HALF_UP)
    return allocated


def register_receipt(
    user,
    items_by_category: dict[str, list[int]],
    payment_method_name: str = "",
    summaries: dict[str, str] | None = None,
) -> str:
    """Registra o recibo de FOTO pendente (ReceiptDraft) em N linhas, uma por
    categoria, atribuindo cada item por ÍNDICE.

    ``items_by_category`` mapeia o NOME da categoria para a lista de ÍNDICES
    (0-based, na ordem em que o recibo foi lido) dos itens daquela categoria.
    Cada item DEVE aparecer em exatamente UMA categoria; a soma usa os valores
    do recibo (fonte da verdade), nunca valores redigitados — então a soma das
    linhas bate com o valor pago e nenhum item é contado duas vezes.

    ``summaries`` (opcional) mapeia categoria → resumo curto do conteúdo (ex.:
    "grãos, legumes e verduras, laticínios"); a descrição fica "<loja> - <resumo>".

    ``payment_method_name`` vazio cai na forma de pagamento lida no cupom; se o
    cupom só disser "Cartão Crédito" (genérico, vários cartões), pergunta qual.
    """
    draft = (
        ReceiptDraft.objects.filter(user=user, status=ReceiptDraftStatus.PENDING)
        .order_by("-created_at")
        .first()
    )
    if draft is None:
        return "Erro: nenhum recibo (foto) pendente para registrar."
    payload = draft.payload or {}
    items = payload.get("items", [])
    n = len(items)
    if n == 0:
        return "Erro: o recibo pendente não tem itens."

    # Cada item em exatamente UMA categoria (impede dupla contagem / omissão).
    assigned = [i for idxs in items_by_category.values() for i in idxs]
    if sorted(assigned) != list(range(n)):
        seen: set[int] = set()
        dups = sorted({i for i in assigned if (i in seen) or seen.add(i)})
        missing = sorted(set(range(n)) - set(assigned))
        out_of_range = sorted(i for i in assigned if i < 0 or i >= n)
        problems = []
        if missing:
            problems.append(f"faltando={missing}")
        if dups:
            problems.append(f"repetidos={dups}")
        if out_of_range:
            problems.append(f"fora do intervalo 0..{n - 1}={out_of_range}")
        return (
            f"Erro: cada um dos {n} itens deve ser atribuído a exatamente UMA "
            f"categoria ({'; '.join(problems)})."
        )

    # Forma de pagamento: o modelo informa; senão, o que foi lido no cupom.
    pm_name = (payment_method_name or "").strip() or str(
        payload.get("payment_hint") or ""
    ).strip()
    payment_method, pm_matches = _resolve_by_name(
        PaymentMethod.objects.filter(user=user, is_active=True), pm_name
    )
    if payment_method is None:
        available = ", ".join(list_payment_methods(user))
        if len(pm_matches) > 1:
            return f"Forma de pagamento '{pm_name}' é ambígua. Qual? {', '.join(pm_matches)}"
        hint = str(payload.get("payment_hint") or "").strip()
        last4 = str(payload.get("card_last4") or "").strip()
        extra = f" O cupom indica '{hint}'." if hint else ""
        if last4:
            extra += f" Cartão final {last4}."
        return (
            f"Qual a forma de pagamento?{extra} Não consegui resolver "
            f"'{pm_name}'. Disponíveis: {available}"
        )

    # Resolve categorias e soma cada grupo pelos VALORES do recibo.
    resolved: dict[str, Category] = {}
    category_sums: dict[str, Decimal] = {}
    for cat_name, idxs in items_by_category.items():
        category, cat_matches = _resolve_by_name(
            Category.objects.filter(user=user), cat_name
        )
        if category is None:
            if len(cat_matches) > 1:
                return (
                    f"Erro: categoria '{cat_name}' é ambígua. "
                    f"Você quis dizer: {', '.join(cat_matches)}?"
                )
            available = ", ".join(list_categories(user))
            return f"Erro: categoria '{cat_name}' não encontrada. Disponíveis: {available}"
        try:
            subtotal = sum(
                (Decimal(str(items[i].get("line_total", "0"))) for i in idxs),
                Decimal("0"),
            )
        except InvalidOperation:
            return f"Erro: valor inválido nos itens da categoria '{cat_name}'."
        resolved[cat_name] = category
        category_sums[cat_name] = subtotal

    try:
        discount_val = Decimal(str(payload.get("discount") or "0"))
    except InvalidOperation:
        discount_val = Decimal("0")
    discount_by_cat = _prorate_discount(category_sums, discount_val)

    store = str(payload.get("store") or "Recibo").strip()
    date_str = payload.get("date")
    try:
        entry_date = date.fromisoformat(date_str) if date_str else timezone.localdate()
    except (ValueError, TypeError):
        entry_date = timezone.localdate()

    summaries = summaries or {}
    created = []
    with transaction.atomic():
        for cat_name, category in resolved.items():
            net = (category_sums[cat_name] - discount_by_cat[cat_name]).quantize(_CENTS)
            summary = (summaries.get(cat_name) or "").strip() or category.name
            description = f"{store} - {summary}".replace(",", " -").strip()
            entry = Entry.objects.create(
                user=user,
                date=entry_date,
                amount=net,
                description=description,
                category=category,
                payment_method=payment_method,
            )
            created.append((category.name, entry.amount))
        draft.status = ReceiptDraftStatus.REGISTERED
        draft.save(update_fields=["status", "updated_at"])

    total_paid = sum((amt for _, amt in created), Decimal("0"))
    lines = "; ".join(f"{name} R$ {amt:.2f}" for name, amt in created)
    return (
        f"✅ Registrado de {store} em {entry_date:%d/%m/%Y} via "
        f"{payment_method.name}: {lines} (total R$ {total_paid:.2f})"
    )


def build_receipt_context(user) -> str:
    """Bloco de contexto do recibo pendente mais recente do usuário (ou "").

    Usado na delegação orquestrador→registrador para que o turno de correção
    ("separe as categorias") tenha os itens já lidos da foto — sem isto o
    registrador roda cego e não consegue ratear.
    """
    draft = (
        ReceiptDraft.objects.filter(user=user, status=ReceiptDraftStatus.PENDING)
        .order_by("-created_at")
        .first()
    )
    if draft is None:
        return ""
    payload = draft.payload or {}
    items = payload.get("items", [])
    # Itens NUMERADOS (índice) — register_receipt atribui cada índice a 1 categoria.
    item_lines = "; ".join(
        f"[{idx}] {i.get('description', '?')} R$ {i.get('line_total', '?')}"
        for idx, i in enumerate(items)
    )
    card_last4 = payload.get("card_last4") or "?"
    return (
        "Contexto de recibo pendente (extraído de foto recente): "
        f"loja={payload.get('store', '?')}, data={payload.get('date', '?')}, "
        f"forma_pagamento={payload.get('payment_hint') or '?'}, "
        f"cartao_final={card_last4}, cartao_inicio={payload.get('card_first_digits') or '?'}, "
        f"desconto={payload.get('discount', '0')}, "
        f"valor_pago={payload.get('amount_paid', '?')}, "
        f"itens(índice INTERNO, NÃO mostrar ao usuário)=[{item_lines}]. Use "
        "register_receipt passando items_by_category como {categoria: [índices]} "
        "(cada índice em UMA só categoria) e summaries {categoria: resumo do "
        "conteúdo}; mostre ao usuário só uma tabela limpa (Categoria | Itens). "
        "Forma de pagamento: bandeira de cartão é genérica — resolva pelo final "
        f'do cartão ({card_last4}) via check_memory; sem regra, pergunte qual '
        "cartão e salve com save_memory_rule. Confirme UMA única vez."
    )


def build_pending_receipt_directive(user) -> str:
    """Diretiva para o ORQUESTRADOR quando há um recibo de foto PENDENTE.

    O turno da foto mostra a tabela e pergunta "Confirma?"; a confirmação do
    usuário ("sim") volta pelo caminho de TEXTO → orquestrador. Sem este aviso o
    orquestrador não sabe que existe um recibo a registrar, NÃO chama
    delegate_registro e ainda responde "registrei" (nada é gravado — bug real do
    recibo MATEUS: draft pendente, 0 lançamentos). A diretiva força a delegação
    e proíbe afirmar registro sem o resultado da ferramenta.
    """
    draft = (
        ReceiptDraft.objects.filter(user=user, status=ReceiptDraftStatus.PENDING)
        .order_by("-created_at")
        .first()
    )
    if draft is None:
        return ""
    payload = draft.payload or {}
    store = str(payload.get("store") or "recibo").strip()
    paid = payload.get("amount_paid")
    paid_str = paid if paid is not None else "?"
    return (
        "⚠️ HÁ UM RECIBO DE FOTO PENDENTE aguardando confirmação para ser "
        f"registrado (loja: {store}, valor pago: {paid_str}). Se a mensagem do "
        "usuário for uma CONFIRMAÇÃO (sim, ok, pode, isso, confirmo, manda, "
        "beleza, fechado, etc.) OU um AJUSTE ao recibo (categorias, forma de "
        "pagamento, loja, data), você DEVE chamar delegate_registro repassando a "
        "mensagem do usuário — é o ÚNICO caminho que grava o recibo. NUNCA diga "
        "que registrou/registramos nem responda 'pronto' sem ter chamado "
        "delegate_registro e recebido o resultado da ferramenta."
    )


def _billing_month(year: int, month: int) -> "date | str":
    """Return a date for the first of the month, or an error string if invalid."""
    try:
        return date(year, month, 1)
    except ValueError:
        return f"Erro: ano/mês inválido ({year}/{month})."


def query_expenses(user, year: int, month: int, category_name: str | None = None) -> str:
    """Query total expenses for a month, optionally filtered by category."""
    bm = _billing_month(year, month)
    if isinstance(bm, str):
        return bm
    billing_month = bm
    qs = Entry.objects.filter(user=user, billing_month=billing_month, amount__gt=0)

    if category_name:
        try:
            category = Category.objects.get(user=user, name=category_name)
        except Category.DoesNotExist:
            return f"Categoria '{category_name}' não encontrada."
        qs = qs.filter(category=category)
        total = qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")
        ceiling_info = ""
        if category.budget_ceiling and category.budget_ceiling > 0:
            pct = total / category.budget_ceiling * 100
            ceiling_info = f" (teto: R$ {category.budget_ceiling:.2f} — {pct:.0f}% do orçamento)"
        return (
            f"Em {month:02d}/{year}, você gastou R$ {total:.2f} com {category_name}{ceiling_info}."
        )

    total = qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    count = qs.count()
    return f"Em {month:02d}/{year}, você gastou R$ {total:.2f} em {count} entradas."


def query_balance(user, year: int, month: int) -> str:
    """Query monthly balance: income, expenses, returns."""
    bm = _billing_month(year, month)
    if isinstance(bm, str):
        return bm
    billing_month = bm

    income = Income.objects.filter(user=user, month=billing_month).aggregate(total=Sum("amount"))[
        "total"
    ] or Decimal("0")

    entries = Entry.objects.filter(user=user, billing_month=billing_month)
    expenses = entries.filter(amount__gt=0).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    returns = abs(
        entries.filter(amount__lt=0).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    )
    balance = income - expenses + returns

    return (
        f"Saldo de {month:02d}/{year}:\n"
        f"- Renda: R$ {income:.2f}\n"
        f"- Gastos: R$ {expenses:.2f}\n"
        f"- Retornos: R$ {returns:.2f}\n"
        f"- Saldo: R$ {balance:.2f}"
    )


def query_budget_status(user, year: int, month: int) -> str:
    """List categories that exceeded or are near their budget ceiling."""
    bm = _billing_month(year, month)
    if isinstance(bm, str):
        return bm
    billing_month = bm

    category_totals = (
        Entry.objects.filter(user=user, billing_month=billing_month, amount__gt=0)
        .values("category__name", "category__budget_ceiling")
        .annotate(total=Sum("amount"))
    )

    over = []
    warning = []
    ok_count = 0

    for ct in category_totals:
        ceiling = ct["category__budget_ceiling"]
        if not ceiling or ceiling <= 0:
            ok_count += 1
            continue
        pct = ct["total"] / ceiling * 100
        if pct >= 100:
            over.append(
                f"🔴 {ct['category__name']}: R$ {ct['total']:.0f} / R$ {ceiling:.0f} ({pct:.0f}%)"
            )
        elif pct >= 90:
            warning.append(
                f"⚠️ {ct['category__name']}: R$ {ct['total']:.0f} / R$ {ceiling:.0f} ({pct:.0f}%)"
            )
        else:
            ok_count += 1

    lines = []
    if over:
        lines.append(f"Categorias acima do teto em {month:02d}/{year}:")
        lines.extend(over)
    if warning:
        lines.append("Categorias perto do teto:")
        lines.extend(warning)
    if ok_count > 0:
        lines.append(f"\n{ok_count} categorias dentro do orçamento.")
    if not over and not warning:
        lines.append(f"Todas as categorias dentro do orçamento em {month:02d}/{year}.")

    return "\n".join(lines)


def query_installments(user) -> str:
    """List active installment plans."""
    plans = InstallmentPlan.objects.filter(user=user).order_by("-date")

    if not plans.exists():
        return "Nenhum parcelamento ativo."

    lines = ["Parcelamentos ativos:"]
    total_monthly = Decimal("0")

    for plan in plans:
        entry_count = Entry.objects.filter(installment_plan=plan).count()
        if entry_count == 0:
            continue
        lines.append(
            f"- {plan.description} ({entry_count}/{plan.num_installments}x) "
            f"— R$ {plan.installment_amount:.2f}/mês"
        )
        total_monthly += plan.installment_amount

    if total_monthly > 0:
        lines.append(f"\nTotal mensal em parcelas: R$ {total_monthly:.2f}")

    return "\n".join(lines)


def create_category(user, name: str, budget_ceiling: str) -> str:
    """Create a new expense category."""
    if Category.objects.filter(user=user, name=name).exists():
        return f"Erro: categoria '{name}' já existe."

    try:
        ceiling = Decimal(budget_ceiling)
    except InvalidOperation:
        return f"Erro: valor de teto inválido '{budget_ceiling}'."

    Category.objects.create(user=user, name=name, budget_ceiling=ceiling)
    return f"Categoria '{name}' criada com teto de R$ {ceiling:.2f}."


def update_category_budget(user, category_name: str, new_ceiling: str) -> str:
    """Update the budget ceiling of an existing category."""
    try:
        category = Category.objects.get(user=user, name=category_name)
    except Category.DoesNotExist:
        return f"Erro: categoria '{category_name}' não encontrada."

    try:
        ceiling = Decimal(new_ceiling)
    except InvalidOperation:
        return f"Erro: valor inválido '{new_ceiling}'."

    old_ceiling = category.budget_ceiling
    category.budget_ceiling = ceiling
    category.save()
    return f"Teto de {category_name} atualizado de R$ {old_ceiling:.2f} para R$ {ceiling:.2f}."


def create_payment_method(user, name: str, pm_type: str, closing_day: str | None = None) -> str:
    """Create a new payment method."""
    if PaymentMethod.objects.filter(user=user, name=name).exists():
        return f"Erro: forma de pagamento '{name}' já existe."

    valid_types = [choice.value for choice in PaymentType]
    if pm_type not in valid_types:
        return f"Erro: tipo inválido '{pm_type}'. Válidos: {', '.join(valid_types)}."

    closing = None
    if closing_day:
        try:
            closing = int(closing_day)
        except ValueError:
            return f"Erro: dia de fechamento inválido '{closing_day}'."

    PaymentMethod.objects.create(user=user, name=name, type=pm_type, closing_day=closing)
    closing_info = f" (fechamento dia {closing})" if closing else ""
    return f"Forma de pagamento '{name}' criada{closing_info}."


def update_income(user, name: str, amount: str, month_str: str) -> str:
    """Create or update income for a specific month."""
    try:
        amount_val = Decimal(amount)
    except InvalidOperation:
        return f"Erro: valor inválido '{amount}'."

    try:
        month = date.fromisoformat(month_str)
    except ValueError:
        return f"Erro: data inválida '{month_str}'. Use formato AAAA-MM-DD."

    income, created = Income.objects.update_or_create(
        user=user,
        name=name,
        month=month,
        defaults={"amount": amount_val},
    )
    action = "criada" if created else "atualizada"
    return f"Renda '{name}' {action}: R$ {amount_val:.2f} em {month:%m/%Y}."


def list_systemic_expenses(user) -> list[str]:
    """List active systemic expense names and default amounts for the user."""
    return [
        f"{s.name} (padrão R$ {s.default_amount:.2f})"
        for s in SystemicExpense.objects.filter(user=user, is_active=True).order_by("name")
    ]


def set_systemic_amount(user, name: str, amount_str: str, month_str: str) -> str:
    """Set the amount of a systemic expense for a specific month."""
    try:
        amount_val = Decimal(amount_str)
    except InvalidOperation:
        return f"Erro: valor inválido '{amount_str}'."

    try:
        month = date.fromisoformat(month_str).replace(day=1)
    except ValueError:
        return f"Erro: data inválida '{month_str}'. Use formato AAAA-MM-DD."

    s = SystemicExpense.objects.filter(user=user, is_active=True, name__iexact=name).first()
    if s is None:
        available = ", ".join(
            SystemicExpense.objects.filter(user=user, is_active=True)
            .order_by("name")
            .values_list("name", flat=True)
        )
        return (
            f"Não encontrei um gasto sistemático chamado '{name}'. "
            f"Disponíveis: {available}. (Nenhuma alteração feita.)"
        )

    existing = Entry.objects.filter(
        user=user,
        systemic_expense=s,
        billing_month=month,
        entry_type=EntryType.SYSTEMIC,
    ).first()

    if existing:
        existing.amount = amount_val
        existing.save(update_fields=["amount", "updated_at"])
    else:
        s.create_monthly_entry(month, amount=amount_val)

    return f"Gasto sistemático '{s.name}' definido para R$ {amount_val:.2f} em {month:%m/%Y}."


VALID_MEMORY_FIELDS = {"category", "payment_method", "description"}


def lookup_memory(user, message: str) -> str:
    """Look up memory rules matching the user's message."""
    rules = find_matching_rules(user, message)
    if not rules:
        return "Nenhuma regra de memória encontrada."

    lines = ["Regras de memória encontradas:"]
    for rule in rules:
        if rule.confidence >= AUTO_APPLY:
            tier = "auto-aplicar"
        elif rule.confidence >= CONFIRM_APPLY:
            tier = "sugerir ao usuário"
        else:
            tier = "perguntar ao usuário"
        lines.append(f"- {rule.field}='{rule.value}' (confiança: {rule.confidence}, {tier})")

    return "\n".join(lines)


async def lookup_memory_async(user, message: str) -> str:
    """Look up memory rules matching the user's message, with semantic fallback."""
    rules = await _sync_to_async(find_matching_rules)(user, message)
    if rules:
        lines = ["Regras de memória encontradas:"]
        for rule in rules:
            if rule.confidence >= AUTO_APPLY:
                tier = "auto-aplicar"
            elif rule.confidence >= CONFIRM_APPLY:
                tier = "sugerir ao usuário"
            else:
                tier = "perguntar ao usuário"
            lines.append(f"- {rule.field}='{rule.value}' (confiança: {rule.confidence}, {tier})")
        return "\n".join(lines)

    # Fallback: semantic search
    query_vector = await get_embedding(message)
    if query_vector:
        matches = await _sync_to_async(find_semantic_matches)(user, query_vector)
        if matches:
            lines = ["Memórias similares encontradas (busca semântica):"]
            for match in matches:
                meta = match.metadata or {}
                field = meta.get("field", "?")
                value = meta.get("value", "?")
                lines.append(f"- {field}='{value}' (texto: '{match.text[:50]}')")
            return "\n".join(lines)

    return "Nenhuma regra de memória encontrada."


def create_memory_rule(user, trigger: str, field: str, value: str) -> str:
    """Create or update a memory rule from user correction."""
    if field not in VALID_MEMORY_FIELDS:
        valid = ", ".join(sorted(VALID_MEMORY_FIELDS))
        return f"Erro: campo '{field}' inválido. Válidos: {valid}."

    rule, created = MemoryRule.objects.update_or_create(
        user=user,
        trigger=trigger.lower(),
        field=field,
        defaults={
            "value": value,
            "confidence": 1.0,
            "source": MemorySource.USER_CORRECTION,
        },
    )
    action = "criada" if created else "atualizada"
    return f"Regra de memória {action}: '{trigger}' → {field}='{value}'."


def list_memory_rules(user) -> str:
    """List all memory rules for the user."""
    rules = MemoryRule.objects.filter(user=user).order_by("trigger", "field")
    if not rules.exists():
        return "Nenhuma regra de memória cadastrada."

    lines = ["Suas regras de memória:"]
    for rule in rules:
        lines.append(
            f"- '{rule.trigger}' → {rule.field}='{rule.value}' (confiança: {rule.confidence})"
        )
    return "\n".join(lines)
