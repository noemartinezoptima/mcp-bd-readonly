from mcp_bd_readonly import tools_catalogo
from mcp_bd_readonly.tools_catalogo import describe_tablas_clave, build_catalogo_tools


class FakeEx:
    def __init__(self):
        self.calls = []

    def run(self, sql, params=None, limit=100):
        self.calls.append(sql)
        table = sql.split("`")[1]
        return ["Field"], [{"Field": f"{table}_col1"}, {"Field": f"{table}_col2"}]


class FakeAudit:
    def __init__(self):
        self.calls = []

    def record(self, tool, who, sql, note=""):
        self.calls.append((tool, who, sql))


def setup_function(_):
    tools_catalogo._cache.clear()


def test_describe_tablas_clave_queries_each_table_once():
    ex = FakeEx()
    out = describe_tablas_clave(ex, ["clientes", "facturas_venta"])
    assert set(out) == {"clientes", "facturas_venta"}
    assert len(ex.calls) == 2


def test_describe_tablas_clave_incluye_nota_polimorfismo():
    ex = FakeEx()
    out = describe_tablas_clave(ex, ["efectos_pago"])
    assert "modelo_id=11" in out["efectos_pago"]["nota"]
    assert "fecha_pagado" in out["efectos_pago"]["nota"]


def test_describe_tablas_clave_usa_cache():
    ex = FakeEx()
    describe_tablas_clave(ex, ["clientes"])
    describe_tablas_clave(ex, ["clientes"])
    assert len(ex.calls) == 1


def test_describe_tablas_clave_default_tablas():
    ex = FakeEx()
    out = describe_tablas_clave(ex)
    assert set(out) == set(tools_catalogo.TABLAS_CLAVE)


def test_tool_wrapper_registra_auditoria():
    ex = FakeEx()
    audit = FakeAudit()
    (tool,) = build_catalogo_tools(ex, audit)
    result = tool(["clientes"])
    assert "clientes" in result
    assert audit.calls[0][0] == "describe_tablas_clave"
