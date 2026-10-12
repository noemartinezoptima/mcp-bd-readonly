from decimal import Decimal

from mcp_bd_readonly.tools_balance import _categoria, balance, build_balance_tools


def test_categoria_clasifica():
    assert _categoria("10") == "patrimonio"
    assert _categoria("21") == "activo_no_corriente"
    assert _categoria("43") == "activo_corriente"
    assert _categoria("40") == "pasivo"
    assert _categoria("57") == "activo_corriente"
    assert _categoria("60") == "gasto"
    assert _categoria("70") == "ingreso"
    assert _categoria("") == "otro"


class FakeEx:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def run(self, sql, params=None, limit=100):
        self.calls.append((sql, params, limit))
        return ["pgc_group", "debe", "haber"], self.rows


def test_balance_cuadra():
    # datos contables balanceados: activo = pasivo + patrimonio + resultado
    ex = FakeEx([
        {"pgc_group": "57", "debe": Decimal("1300.00"), "haber": Decimal("0.00")},  # tesorería
        {"pgc_group": "40", "debe": Decimal("0.00"), "haber": Decimal("200.00")},  # proveedores
        {"pgc_group": "10", "debe": Decimal("0.00"), "haber": Decimal("700.00")},  # capital
        {"pgc_group": "70", "debe": Decimal("0.00"), "haber": Decimal("600.00")},  # ingresos
        {"pgc_group": "60", "debe": Decimal("200.00"), "haber": Decimal("0.00")},  # gastos
    ])
    r = balance(ex)
    assert r["activo"]["total"] == Decimal("1300.00")
    assert r["pasivo"]["total"] == Decimal("200.00")
    assert r["patrimonio"]["total"] == Decimal("700.00")
    assert r["ingresos"] == Decimal("600.00")
    assert r["gastos"] == Decimal("200.00")
    assert r["resultado"] == Decimal("400.00")
    # cuadre: activo − (pasivo+patrimonio) == resultado
    assert r["cuadra"] == r["resultado"] == Decimal("400.00")
    assert r["activo"]["total_es"] == "1.300,00 €"


def test_build_balance_tools_registers_one():
    tools = build_balance_tools(executor=None, audit=None)
    names = {t.__name__ for t in tools}
    assert names == {"balance"}
