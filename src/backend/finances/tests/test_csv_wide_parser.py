import io
from datetime import date
from decimal import Decimal

from finances.services.csv_parser import parse_month_header, parse_wide_csv


class TestParseMonthHeader:
    def test_parses_abbreviated_ptbr_month(self):
        assert parse_month_header("out./2025") == date(2025, 10, 1)
        assert parse_month_header("jan./2026") == date(2026, 1, 1)
        assert parse_month_header("dez./2027") == date(2027, 12, 1)

    def test_tolerates_whitespace_and_case(self):
        assert parse_month_header("  MAI./2026 ") == date(2026, 5, 1)

    def test_returns_none_for_non_month_header(self):
        assert parse_month_header("nome") is None
        assert parse_month_header("categoria") is None


class TestParseWideCsv:
    def test_unpivots_income_rows_skipping_empty_cells(self):
        content = (
            "nome,nov./2025,dez./2025,jan./2026\n"
            'Salário,"R$ 5.815,91","R$ 5.815,91","R$ 10.824,55"\n'
            '13°,,"R$ 3.998,74","R$ 9.879,28"\n'
        )
        rows = parse_wide_csv(io.StringIO(content), key_fields=["nome"])

        assert rows[0]["nome"] == "Salário"
        assert rows[0]["months"] == {
            date(2025, 11, 1): Decimal("5815.91"),
            date(2025, 12, 1): Decimal("5815.91"),
            date(2026, 1, 1): Decimal("10824.55"),
        }
        # Empty November cell is skipped for 13°
        assert rows[1]["nome"] == "13°"
        assert rows[1]["months"] == {
            date(2025, 12, 1): Decimal("3998.74"),
            date(2026, 1, 1): Decimal("9879.28"),
        }

    def test_supports_multiple_key_fields(self):
        content = (
            "nome,categoria,nov./2025,dez./2025\n"
            'Enel,Custeio,"R$ 460,00","R$ 579,25"\n'
        )
        rows = parse_wide_csv(io.StringIO(content), key_fields=["nome", "categoria"])

        assert rows[0]["nome"] == "Enel"
        assert rows[0]["categoria"] == "Custeio"
        assert rows[0]["months"] == {
            date(2025, 11, 1): Decimal("460.00"),
            date(2025, 12, 1): Decimal("579.25"),
        }

    def test_skips_rows_with_empty_key(self):
        content = "nome,nov./2025\n,\"R$ 10,00\"\nReal,\"R$ 20,00\"\n"
        rows = parse_wide_csv(io.StringIO(content), key_fields=["nome"])
        assert len(rows) == 1
        assert rows[0]["nome"] == "Real"

    def test_raises_when_key_field_missing_from_headers(self):
        import pytest

        content = "nome,nov./2025\nEnel,\"R$ 10,00\"\n"
        with pytest.raises(ValueError):
            parse_wide_csv(io.StringIO(content), key_fields=["nome", "categoria"])
