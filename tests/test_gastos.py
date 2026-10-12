from decimal import Decimal

from mcp_bd_readonly.tools_gastos import (
    build_gastos_tools,
    facturas_compra,
    margen,
    pnl,
    resumen_gastos_por_tipo,
)


class FakeEx:
    def __init__(self, facturas=None):
        self.facturas = facturas or []
        self.calls = []

    def run(self, sql, params=None, limit=100):
        self.calls.append((sql, params, limit))
        if "facturas_venta" in sql:
            return ["t", "i"], [{"t": Decimal("1000.00"), "i": Decimal("210.00")}]
        if "GROUP BY coste_directo" in sql:
            return ["coste_directo", "c"], [
                {"coste_directo": 1, "c": Decimal("400.00")},
                {"coste_directo": 0, "c": Decimal("100.00")},
            ]
        if "tipos_de_gasto" in sql:
            return ["tipo", "n", "total", "base"], [
                {"tipo": "Material", "n": 2, "total": Decimal("300.00"), "base": Decimal("250.00")},
            ]
        if "COUNT(*) n FROM facturas_compra" in sql:
            t = sum((f.get("total_euros") or Decimal("0")) for f in self.facturas)
            return ["t", "n"], [{"t": t, "n": len(self.facturas)}]
        return (
            ["codigo", "fecha_factura", "proveedor_nombre", "base_euros", "iva_euros", "total_euros", "pagada"],
            self.facturas,
        )


def _fc(**kw):
    base = {
        "codigo": "G-001", "fecha_factura": "2026-06-10", "proveedor_nombre": "Acme SL",
        "base_euros": Decimal("100.00"), "iva_euros": Decimal("21.00"),
        "total_euros": Decimal("121.00"), "pagada": 0,
    }
    base.update(kw)
    return base


def test_facturas_compra_basic():
    ex = FakeEx([_fc(), _fc(codigo="G-002", total_euros=Decimal("242.00"), base_euros=Decimal("200.00"), iva_euros=Decimal("42.00"))])
    r = facturas_compra(ex, "2026-06-01", "2026-06-30")
    assert r["n_total"] == 2
    assert r["total_periodo"] == Decimal("363.00")
    assert r["total_periodo_es"] == "363,00 €"
    assert r["facturas"][0]["proveedor"] == "Acme SL"
    assert r["facturas"][0]["pagada"] is False
    _, list_params, list_limit = ex.calls[1]
    assert list_params == ["2026-06-01", "2026-06-30", 200]
    assert list_limit is None


def test_facturas_compra_filtros():
    ex = FakeEx([])
    facturas_compra(ex, "2026-01-01", "2026-12-31", proveedor="Acme", tipo_gasto_id=607, solo_pendientes=True)
    agg_sql, agg_params, _ = ex.calls[0]
    assert "proveedor_nombre LIKE %s" in agg_sql
    assert "tipo_gasto_id = %s" in agg_sql
    assert "pagada = 0" in agg_sql
    assert agg_params == ["2026-01-01", "2026-12-31", "%Acme%", "Acme", 607]


def test_resumen_gastos_por_tipo():
    ex = FakeEx([])
    r = resumen_gastos_por_tipo(ex, "2026-01-01", "2026-12-31")
    assert r["por_tipo"][0]["tipo"] == "Material"
    assert r["por_tipo"][0]["total"] == Decimal("300.00")


def test_margen_neto_de_iva():
    ex = FakeEx([])
    r = margen(ex, "2026-01-01", "2026-12-31")
    # ventas netas = 1000 - 210 = 790; costes directos = 400
    assert r["ventas_netas"] == Decimal("790.00")
    assert r["costes_directos"] == Decimal("400.00")
    assert r["margen"] == Decimal("390.00")
    assert r["margen_pct"] == 49.4


def test_pnl():
    ex = FakeEx([])
    r = pnl(ex, "2026-01-01", "2026-12-31")
    assert r["ingresos"] == Decimal("790.00")
    assert r["costes_directos"] == Decimal("400.00")
    assert r["margen_bruto"] == Decimal("390.00")
    assert r["costes_indirectos"] == Decimal("100.00")
    assert r["resultado"] == Decimal("290.00")
    assert r["margen_bruto_pct"] == 49.4
    assert r["resultado_pct"] == 36.7


def test_build_gastos_tools_registers_four():
    tools = build_gastos_tools(executor=None, audit=None)
    names = {t.__name__ for t in tools}
    assert names == {"facturas_compra", "resumen_gastos_por_tipo", "margen", "pnl"}
