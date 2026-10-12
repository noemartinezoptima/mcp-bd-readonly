from datetime import date, datetime
from decimal import Decimal

from mcp_bd_readonly.format_es import _dec, exact_sum, fmt_date, fmt_dias, fmt_mes, fmt_money


def test_fmt_money_es():
    assert fmt_money(Decimal("1234567.89")) == "1.234.567,89 €"
    assert fmt_money(Decimal("0")) == "0,00 €"
    assert fmt_money(Decimal("-1234.5")) == "-1.234,50 €"
    assert fmt_money(Decimal("5")) == "5,00 €"
    assert fmt_money("1234.5") == "1.234,50 €"
    assert fmt_money(None) == "0,00 €"


def test_fmt_date_es():
    assert fmt_date(date(2026, 9, 8)) == "08/09/2026"
    assert fmt_date(datetime(2026, 9, 8, 14, 30)) == "08/09/2026"


def test_exact_sum():
    assert exact_sum([Decimal("10.99"), Decimal("0.01")]) == Decimal("11.00")
    assert exact_sum([Decimal("1.005"), Decimal("1.005")]) == Decimal("2.01")  # ROUND_HALF_UP
    assert exact_sum([Decimal("1.005"), Decimal("1.005")]) != Decimal("2.00")  # never round-even
    assert exact_sum([Decimal("0.1"), "0.2", None]) == Decimal("0.30")


def test_fmt_mes_es():
    assert fmt_mes("2026-01") == "01/2026"
    assert fmt_mes("2025-12") == "12/2025"


def test_fmt_dias_es():
    assert fmt_dias(70.5) == "70,5 d"
    assert fmt_dias(Decimal("6.1")) == "6,1 d"
    assert fmt_dias(0) == "0,0 d"


def test_dec_coercion():
    assert _dec(None) == Decimal("0")
    assert _dec(5) == Decimal("5")
    assert _dec("1.25") == Decimal("1.25")
    assert _dec(Decimal("3.14")) == Decimal("3.14")
