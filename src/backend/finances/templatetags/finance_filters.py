from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Access dict value by key in templates: {{ dict|get_item:key }}"""
    if isinstance(dictionary, dict):
        return dictionary.get(key, "")
    return ""


@register.filter
def brl(value):
    """Format a numeric value as pt-BR currency: 4000 -> 'R$ 4.000,00'.

    None/blank render as 'R$ 0,00'; unparseable values are returned unchanged.
    """
    if value is None or value == "":
        value = 0
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return value
    negative = amount < 0
    # US grouping then swap separators to pt-BR (1,234.56 -> 1.234,56)
    formatted = f"{abs(amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-R$ {formatted}" if negative else f"R$ {formatted}"


@register.filter
def money(value):
    """Render a currency value in the ledger monospaced style.

    Wraps :func:`brl` output in ``<span class="amount">`` so figures use the
    tabular mono numerals defined in the design system. Use this in templates
    for displayed amounts; use ``brl`` when you need the plain string.
    """
    return format_html('<span class="amount">{}</span>', brl(value))
