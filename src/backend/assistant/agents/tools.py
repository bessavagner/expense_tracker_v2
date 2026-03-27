from datetime import date
from decimal import Decimal, InvalidOperation

from finances.models import Category, Entry, PaymentMethod


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
