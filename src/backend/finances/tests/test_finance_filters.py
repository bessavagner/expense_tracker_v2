from decimal import Decimal

from django.utils.safestring import SafeString

from finances.templatetags.finance_filters import brl, money


class TestMoneyFilter:
    def test_wraps_brl_in_amount_span(self):
        result = money(Decimal("4000.00"))
        assert result == '<span class="amount">R$ 4.000,00</span>'

    def test_is_marked_safe_html(self):
        assert isinstance(money(Decimal("1.00")), SafeString)

    def test_handles_none_and_negative(self):
        assert money(None) == '<span class="amount">R$ 0,00</span>'
        assert money(Decimal("-100.50")) == '<span class="amount">-R$ 100,50</span>'


class TestBrlFilter:
    def test_formats_thousands_and_decimals_ptbr(self):
        assert brl(Decimal("4000.00")) == "R$ 4.000,00"
        assert brl(Decimal("1599.20")) == "R$ 1.599,20"

    def test_formats_small_value(self):
        assert brl(Decimal("166.65")) == "R$ 166,65"

    def test_formats_negative(self):
        assert brl(Decimal("-100.50")) == "-R$ 100,50"

    def test_accepts_string_and_float(self):
        assert brl("32.91") == "R$ 32,91"
        assert brl(50) == "R$ 50,00"

    def test_none_and_blank_render_as_zero(self):
        assert brl(None) == "R$ 0,00"
        assert brl("") == "R$ 0,00"

    def test_invalid_returns_input_unchanged(self):
        assert brl("abc") == "abc"
