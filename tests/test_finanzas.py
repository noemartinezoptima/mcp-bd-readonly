from decimal import Decimal
from mcp_bd_readonly.tools_finanzas import (
    cuadre_factura, facturas_venta, resumen_iva, remesas_pendientes,
    build_finanzas_tools,
)


class FakeEx:
    def __init__(self, default_cols=None, default_rows=None):
        self._default_cols = default_cols or []
        self._default_rows = default_rows or []
        self.calls = []

    def run(self, sql, params=None, limit=100):
        self.calls.append((sql, params, limit))
        if "lineas" in sql:
            return ["total_euros"], [{"total_euros": Decimal("110.00")}, {"total_euros": Decimal("10.00")}]
        if "COUNT(*)" in sql or sql.strip().startswith("SELECT COALESCE(SUM"):
            t = sum((r.get("total_euros") or Decimal("0")) for r in self._default_rows)
            return ["t", "n"], [{"t": t, "n": len(self._default_rows)}]
        if not self._default_rows and "WHERE id=%s" in sql:
            return ["total_euros"], [{"total_euros": Decimal("120.00")}]
        return self._default_cols, self._default_rows


class FakeAudit:
    def __init__(self):
        self.calls = []

    def record(self, tool, who, sql, note=""):
        self.calls.append((tool, who, sql))


def test_cuadre_ok():
    res = cuadre_factura(FakeEx(), 1)
    assert res["exists"] is True
    assert res["ok"] is True
    assert res["header_total"] == Decimal("120.00")
    assert res["lineas_sum"] == Decimal("120.00")


def test_cuadre_diff():
    class D(FakeEx):
        def run(self, sql, params=None, limit=100):
            if "lineas" in sql:
                return ["total_euros"], [{"total_euros": Decimal("100.00")}]
            return ["total_euros"], [{"total_euros": Decimal("120.00")}]

    res = cuadre_factura(D(), 1)
    assert res["exists"] is True
    assert res["ok"] is False
    assert res["diff"] == Decimal("-20.00")


def test_cuadre_no_header():
    class NoHeader(FakeEx):
        def run(self, sql, params=None, limit=100):
            if "lineas" in sql:
                return ["total_euros"], [{"total_euros": Decimal("50.00")}]
            return ["total_euros"], []

    res = cuadre_factura(NoHeader(), 999)
    assert res["ok"] is False
    assert res["exists"] is False
    assert res["header_total"] == Decimal("0")
    assert res["lineas_sum"] == Decimal("0.00")


def test_facturas_venta_basic():
    ex = FakeEx(
        default_cols=["codigo", "fecha_factura", "base_moneda", "iva_euros", "total_euros", "estado_id"],
        default_rows=[
            {"codigo": "F-001", "fecha_factura": "2026-08-01", "base_moneda": Decimal("100.00"),
             "iva_euros": Decimal("21.00"), "total_euros": Decimal("121.00"), "estado_id": 1},
            {"codigo": "F-002", "fecha_factura": "2026-08-15", "base_moneda": Decimal("200.00"),
             "iva_euros": Decimal("42.00"), "total_euros": Decimal("242.00"), "estado_id": 2},
        ],
    )
    result = facturas_venta(ex, "2026-08-01", "2026-08-31")
    assert len(result["facturas"]) == 2
    f1 = result["facturas"][0]
    assert f1["codigo"] == "F-001"
    assert f1["base"] == Decimal("100.00")
    assert f1["iva"] == Decimal("21.00")
    assert f1["total"] == Decimal("121.00")
    assert f1["estado_id"] == 1
    assert result["total_periodo"] == Decimal("363.00")
    assert result["total_periodo_es"] == "363,00 €"
    assert result["n_total"] == 2
    assert result["limit_aplicado"] == 200
    list_sql, list_params, list_limit = ex.calls[1]
    assert "LIMIT %s" in list_sql
    assert list_params == ["2026-08-01", "2026-08-31", 200]
    assert list_limit is None


def test_facturas_venta_with_client():
    ex = FakeEx(
        default_cols=["codigo", "fecha_factura", "base_moneda", "iva_euros", "total_euros", "estado_id"],
        default_rows=[],
    )
    facturas_venta(ex, "2026-08-01", "2026-08-31", cliente=5)
    agg_sql, agg_params, agg_limit = ex.calls[0]
    assert "cliente_id = %s" in agg_sql
    assert agg_params == ["2026-08-01", "2026-08-31", 5]
    assert agg_limit == 1
    list_sql, list_params, list_limit = ex.calls[1]
    assert "cliente_id = %s" in list_sql
    assert list_params == ["2026-08-01", "2026-08-31", 5, 200]
    assert list_limit is None


def test_facturas_venta_no_client():
    ex = FakeEx(
        default_cols=["codigo", "fecha_factura", "base_moneda", "iva_euros", "total_euros", "estado_id"],
        default_rows=[],
    )
    facturas_venta(ex, "2026-08-01", "2026-08-31")
    agg_sql, agg_params, agg_limit = ex.calls[0]
    assert "cliente_id" not in agg_sql
    assert agg_params == ["2026-08-01", "2026-08-31"]
    assert agg_limit == 1
    list_sql, list_params, list_limit = ex.calls[1]
    assert "cliente_id" not in list_sql
    assert list_params == ["2026-08-01", "2026-08-31", 200]
    assert list_limit is None


def test_resumen_iva_quarter2():
    ex = FakeEx(
        default_cols=["base_moneda", "iva_euros", "total_euros"],
        default_rows=[
            {"base_moneda": Decimal("1000.00"), "iva_euros": Decimal("210.00"), "total_euros": Decimal("1210.00")},
        ],
    )
    result = resumen_iva(ex, 2, 2026)
    sql, params, limit = ex.calls[0]
    assert limit is None
    assert params[0] == "2026-04-01 00:00:00"
    assert params[1] == "2026-07-01 00:00:00"
    assert result["base"] == Decimal("1000.00")
    assert result["iva"] == Decimal("210.00")
    assert result["total"] == Decimal("1210.00")
    assert result["base_es"] == "1.000,00 €"
    assert result["iva_es"] == "210,00 €"
    assert result["total_es"] == "1.210,00 €"


def test_resumen_iva_quarter3():
    ex = FakeEx(
        default_cols=["base_moneda", "iva_euros", "total_euros"],
        default_rows=[],
    )
    result = resumen_iva(ex, 3, 2026)
    sql, params, _limit = ex.calls[0]
    assert params[0] == "2026-07-01 00:00:00"
    assert params[1] == "2026-10-01 00:00:00"
    assert result["base"] == Decimal("0.00")


def test_remesas_pendientes():
    ex = FakeEx(
        default_cols=["codigo", "fecha_emision", "fecha_vencimiento", "total_euros", "estado_id", "regularizado"],
        default_rows=[
            {"codigo": "R-001", "fecha_emision": "2026-07-01", "fecha_vencimiento": "2026-08-01",
             "total_euros": Decimal("500.00"), "estado_id": 1, "regularizado": 0},
            {"codigo": "R-002", "fecha_emision": "2026-07-15", "fecha_vencimiento": None,
             "total_euros": Decimal("750.50"), "estado_id": 2, "regularizado": 0},
        ],
    )
    result = remesas_pendientes(ex)
    assert result["total"] == Decimal("2")
    assert result["limit_aplicado"] == 50
    assert len(result["pendientes"]) == 2
    r0 = result["pendientes"][0]
    assert r0["codigo"] == "R-001"
    assert r0["fecha_vencimiento"] == "2026-08-01"
    assert r0["total_euros"] == Decimal("500.00")
    assert r0["estado_id"] == 1
    assert r0["regularizado"] == 0
    assert result["pendientes"][1]["fecha_vencimiento"] is None
    sql, params, _limit = ex.calls[1]
    assert "regularizado = 0" in sql
    assert "deleted_at IS NULL" in sql
    assert "LIMIT %s" in sql
    assert params == [50]


def test_build_finanzas_tools_registers_four():
    tools = build_finanzas_tools(executor=None, audit=None)
    names = {t.__name__ for t in tools}
    assert names == {"facturas_venta", "resumen_iva", "remesas_pendientes", "cuadre_factura"}


def test_build_finanzas_tools_audit():
    audit = FakeAudit()
    ex = FakeEx(
        default_cols=["codigo", "fecha_emision", "fecha_vencimiento", "total_euros", "estado_id", "regularizado"],
        default_rows=[
            {"codigo": "R-001", "fecha_emision": "2026-07-01", "fecha_vencimiento": "2026-08-01",
             "total_euros": Decimal("500.00"), "estado_id": 1, "regularizado": 0},
        ],
    )
    tools = build_finanzas_tools(ex, audit)
    fn_map = {t.__name__: t for t in tools}
    result = fn_map["remesas_pendientes"]()
    assert len(result["pendientes"]) == 1
    assert result["total"] == Decimal("1")
    assert len(audit.calls) == 1
    assert audit.calls[0][0] == "remesas_pendientes"
    assert audit.calls[0][1] == "mcp"

def test_remesas_pendientes_count_true():
    ex = FakeEx(
        default_cols=["codigo", "fecha_emision", "fecha_vencimiento", "total_euros", "estado_id", "regularizado"],
        default_rows=[
            {"codigo": "R-001", "fecha_emision": "2026-07-01", "fecha_vencimiento": "2026-08-01",
             "total_euros": Decimal("500.00"), "estado_id": 1, "regularizado": 0},
            {"codigo": "R-002", "fecha_emision": "2026-07-15", "fecha_vencimiento": "2026-09-15",
             "total_euros": Decimal("750.50"), "estado_id": 2, "regularizado": 0},
        ],
    )
    result = remesas_pendientes(ex)
    assert result["total"] == Decimal("2")
    assert len(result["pendientes"]) == 2
