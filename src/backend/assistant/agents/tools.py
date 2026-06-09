from datetime import date
from decimal import Decimal, InvalidOperation

from asgiref.sync import sync_to_async as _sync_to_async
from django.db.models import Sum

from assistant.agents.memory import (
    AUTO_APPLY,
    CONFIRM_APPLY,
    find_matching_rules,
    find_semantic_matches,
)
from assistant.models import MemoryRule, MemorySource
from assistant.services.embedding import get_embedding
from finances.models import Category, Entry, Income, InstallmentPlan, PaymentMethod
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


def create_entry(
    user,
    date_str: str,
    amount_str: str,
    description: str,
    category_name: str,
    payment_method_name: str,
) -> str:
    """Create an expense entry. Returns a confirmation or error message."""
    # Validate category
    try:
        category = Category.objects.get(user=user, name=category_name)
    except Category.DoesNotExist:
        available = ", ".join(list_categories(user))
        return f"Erro: categoria '{category_name}' não encontrada. Disponíveis: {available}"

    # Validate payment method
    try:
        payment_method = PaymentMethod.objects.get(
            user=user, name=payment_method_name, is_active=True
        )
    except PaymentMethod.DoesNotExist:
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
