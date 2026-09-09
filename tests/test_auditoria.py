from decimal import Decimal

from mcp_bd_readonly.tools_auditoria import (
    clasificar_materialidad,
    conciliar_remesas,
    saldos_cliente,
    excepciones,
    informe_financiero,
    build_auditoria_tools,
)


class FakeEx:
    def __init__(self, default_cols=None, default_rows=None):
        self._default_cols = default_cols or []
        self._default_rows = default_rows or []
        self.calls = []

    def run(self, sql, params=None, limit=100):
        self.calls.append((sql, params, limit))
        return self._default_cols, self._default_rows


class FakeAudit:
    def __init__(self):
        self.calls = []

    def record(self, tool, who, sql, note=""):
        self.calls.append((tool, who, sql))


def test_clasificar_materialidad():
    assert clasificar_materialidad(Decimal("5"), Decimal("100")) == "CRITICAL"  # 5%
    assert clasificar_materialidad(Decimal("1"), Decimal("100")) == "WARNING"  # 1%
    assert clasificar_materialidad(Decimal("0.05"), Decimal("100")) == "INFO"  # 0.05%
    assert clasificar_materialidad(Decimal("10"), Decimal("100")) == "CRITICAL"  # 10%
    assert clasificar_materialidad(Decimal("5"), Decimal("0")) == "INFO"  # base<=0


def test_saldos_cliente_dispatch():
    ex = FakeEx()

    def run(sql, params=None, limit=100):
        ex.calls.append((sql, params, limit))
        if "vista_efectos_pago" in sql:
            return ["v"], [{"v": Decimal("500")}]
        return ["v"], [{"v": Decimal("1200")}]

    ex.run = run
    res = saldos_cliente(ex, 7)
    assert res["cliente_id"] == 7
    assert res["facturado"] == Decimal("1200")
    assert res["cobrado"] == Decimal("500")
    assert res["pendiente"] == Decimal("700")
    assert res["pendiente_es"] == "700,00 €"


def test_conciliar_remesas_dispatch():
    ex = FakeEx()

    def run(sql, params=None, limit=100):
        ex.calls.append((sql, params, limit))
        if "fecha_pagado IS NOT NULL" in sql:
            return ["v"], [{"v": Decimal("7500")}]
        return ["v"], [{"v": Decimal("10000")}]

    ex.run = run
    res = conciliar_remesas(ex)
    assert res["emitido"] == Decimal("10000")
    assert res["acreditado"] == Decimal("7500")
    assert res["pendiente"] == Decimal("2500")
    assert res["pendiente_es"] == "2.500,00 €"


def test_excepciones_filtra_umbral():
    ex = FakeEx()

    def run(sql, params=None, limit=100):
        ex.calls.append((sql, params, limit))
        return ["codigo", "fecha_factura", "base_moneda", "iva_euros", "total_euros", "estado_id"], [
            {"codigo": "F-001", "fecha_factura": "2026-08-01", "base_moneda": Decimal("400.00"),
             "iva_euros": Decimal("84.00"), "total_euros": Decimal("500.00"), "estado_id": 1},
            {"codigo": "F-002", "fecha_factura": "2026-08-05", "base_moneda": Decimal("1000.00"),
             "iva_euros": Decimal("210.00"), "total_euros": Decimal("1500.00"), "estado_id": 2},
            {"codigo": "F-003", "fecha_factura": "2026-08-10", "base_moneda": Decimal("6000.00"),
             "iva_euros": Decimal("1260.00"), "total_euros": Decimal("8000.00"), "estado_id": 3},
        ]

    ex.run = run
    res = excepciones(ex, "2026-08-01", "2026-08-31", Decimal("1000"))
    _sql, _params, limit_kw = ex.calls[0]
    assert limit_kw is None
    assert len(res["excepciones"]) == 2
    assert [e["severidad"] for e in res["excepciones"]] == ["CRITICAL", "CRITICAL"]
    assert res["resumen"] == {"CRITICAL": 2, "WARNING": 0, "INFO": 0}
    assert res["excepciones"][0]["codigo"] == "F-002"
    assert res["excepciones"][0]["total"] == Decimal("1500.00")
    assert "€" in res["excepciones"][0]["total_es"]


def test_informe_financiero_markdown_y_csv():
    ex = FakeEx()

    def run(sql, params=None, limit=100):
        ex.calls.append((sql, params, limit))
        return ["codigo", "fecha_factura", "base_moneda", "iva_euros", "total_euros", "estado_id"], [
            {"codigo": "F-001", "fecha_factura": "2026-08-01", "base_moneda": Decimal("100.00"),
             "iva_euros": Decimal("21.00"), "total_euros": Decimal("121.00"), "estado_id": 1},
        ]

    ex.run = run
    res = informe_financiero(ex, "2026-08-01", "2026-08-31")
    assert "# Informe financiero" in res["markdown"]
    assert "| F-001 |" in res["markdown"]
    lines = res["csv"].strip().splitlines()
    assert lines[0] == "codigo;base;iva;total"
    assert "F-001;100.00;21.00;121.00" in lines[1]


def test_build_auditoria_tools_registers_four():
    tools = build_auditoria_tools(executor=None, audit=None)
    names = {t.__name__ for t in tools}
    assert names == {"conciliar_remesas", "saldos_cliente", "excepciones", "informe_financiero"}


def test_build_auditoria_tools_audit():
    audit = FakeAudit()
    ex = FakeEx()

    def run(sql, params=None, limit=100):
        ex.calls.append((sql, params, limit))
        return ["v"], [{"v": Decimal("100")}]

    ex.run = run
    tools = build_auditoria_tools(ex, audit)
    fn_map = {t.__name__: t for t in tools}
    result = fn_map["conciliar_remesas"]()
    assert result["emitido"] == Decimal("100")
    assert len(audit.calls) == 1
    assert audit.calls[0][0] == "conciliar_remesas"
    assert audit.calls[0][1] == "mcp"
