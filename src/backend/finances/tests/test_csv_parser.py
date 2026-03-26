import io
from datetime import date
from decimal import Decimal

import pytest

from finances.services.csv_parser import (
    detect_columns,
    parse_amount,
    parse_csv_rows,
    parse_date,
)


class TestParseAmount:
    def test_with_r_prefix(self):
        assert parse_amount("R$ 42,00") == Decimal("42.00")

    def test_with_thousand_separator(self):
        assert parse_amount("R$ 1.300,00") == Decimal("1300.00")

    def test_negative(self):
        assert parse_amount("-R$ 226,21") == Decimal("-226.21")

    def test_no_prefix(self):
        assert parse_amount("30,5") == Decimal("30.50")

    def test_no_prefix_integer(self):
        assert parse_amount("100") == Decimal("100")

    def test_whitespace(self):
        assert parse_amount("  R$  42,00  ") == Decimal("42.00")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            parse_amount("")

    def test_non_numeric(self):
        with pytest.raises(ValueError):
            parse_amount("abc")


class TestParseDate:
    def test_standard_format(self):
        assert parse_date("01/03/2026") == date(2026, 3, 1)

    def test_single_digit_day(self):
        assert parse_date("1/3/2026") == date(2026, 3, 1)

    def test_invalid_date(self):
        with pytest.raises(ValueError):
            parse_date("32/13/2026")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            parse_date("")


class TestDetectColumns:
    def test_regular_entries_headers(self):
        headers = ["data", "valor", "descrição", "categoria", "forma"]
        mapping = detect_columns(headers, import_type="regular")
        assert mapping == {
            "date": 0,
            "amount": 1,
            "description": 2,
            "category": 3,
            "payment_method": 4,
        }

    def test_installment_headers(self):
        headers = ["data", "valor", "descrição", "categoria", "forma", "parcelas", "valor_parcela"]
        mapping = detect_columns(headers, import_type="installment")
        assert mapping == {
            "date": 0,
            "total_amount": 1,
            "description": 2,
            "category": 3,
            "payment_method": 4,
            "num_installments": 5,
            "installment_amount": 6,
        }

    def test_case_insensitive(self):
        headers = ["Data", "Valor", "Descrição", "Categoria", "Forma"]
        mapping = detect_columns(headers, import_type="regular")
        assert mapping["date"] == 0

    def test_descricao_without_accent(self):
        headers = ["data", "valor", "descricao", "categoria", "forma"]
        mapping = detect_columns(headers, import_type="regular")
        assert mapping["description"] == 2

    def test_missing_required_column(self):
        headers = ["data", "valor"]
        mapping = detect_columns(headers, import_type="regular")
        assert "description" not in mapping  # missing, not mapped


class TestParseCsvRows:
    def test_parse_regular_entries(self):
        csv_content = (
            "data,valor,descrição,categoria,forma\n"
            '01/03/2026,"R$ 42,00",Heineken - bebida,Álcool,Pix\n'
            '01/03/2026,"R$ 14,00",Disk Bebida,Lanche,Pix\n'
        )
        mapping = {"date": 0, "amount": 1, "description": 2, "category": 3, "payment_method": 4}
        rows = parse_csv_rows(io.StringIO(csv_content), mapping, import_type="regular")
        assert len(rows) == 2
        assert rows[0]["date"] == "2026-03-01"
        assert rows[0]["amount"] == "42.00"
        assert rows[0]["description"] == "Heineken - bebida"
        assert rows[0]["category"] == "Álcool"
        assert rows[0]["payment_method"] == "Pix"

    def test_parse_installments(self):
        csv_content = (
            "data,valor,descrição,categoria,forma,parcelas,valor_parcela\n"
            '01/11/2025,"R$ 193,19",Mercado Livre - Camisetas,Roupa,Crédito C6,2,"R$ 96,60"\n'
        )
        mapping = {
            "date": 0,
            "total_amount": 1,
            "description": 2,
            "category": 3,
            "payment_method": 4,
            "num_installments": 5,
            "installment_amount": 6,
        }
        rows = parse_csv_rows(io.StringIO(csv_content), mapping, import_type="installment")
        assert len(rows) == 1
        assert rows[0]["total_amount"] == "193.19"
        assert rows[0]["num_installments"] == "2"
        assert rows[0]["installment_amount"] == "96.60"

    def test_invalid_row_marked_as_error(self):
        csv_content = (
            "data,valor,descrição,categoria,forma\n"
            '01/03/2026,"R$ 42,00",Good entry,Álcool,Pix\n'
            'invalid-date,"R$ 10,00",Bad entry,Lanche,Pix\n'
        )
        mapping = {"date": 0, "amount": 1, "description": 2, "category": 3, "payment_method": 4}
        rows = parse_csv_rows(io.StringIO(csv_content), mapping, import_type="regular")
        assert rows[0]["status"] == "ok"
        assert rows[1]["status"] == "error"
        assert "date" in rows[1].get("error", "").lower()

    def test_empty_amount_marked_as_error(self):
        csv_content = (
            "data,valor,descrição,categoria,forma\n01/03/2026,,Missing amount,Álcool,Pix\n"
        )
        mapping = {"date": 0, "amount": 1, "description": 2, "category": 3, "payment_method": 4}
        rows = parse_csv_rows(io.StringIO(csv_content), mapping, import_type="regular")
        assert rows[0]["status"] == "error"
