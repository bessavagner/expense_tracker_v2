from decimal import Decimal

from finances.templatetags.finance_filters import brl


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
