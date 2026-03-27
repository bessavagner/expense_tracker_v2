from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Sum

from finances.models import Category, Entry, Income, InstallmentPlan, PaymentMethod


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


def query_expenses(user, year: int, month: int, category_name: str | None = None) -> str:
    """Query total expenses for a month, optionally filtered by category."""
    billing_month = date(year, month, 1)
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
    billing_month = date(year, month, 1)

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
    billing_month = date(year, month, 1)

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
