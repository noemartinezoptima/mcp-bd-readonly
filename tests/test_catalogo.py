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
    tools = build_catalogo_tools(ex, audit)
    assert len(tools) == 2
    tool = tools[0]
    result = tool(["clientes"])
    assert "clientes" in result
    assert audit.calls[0][0] == "describe_tablas_clave"


def test_detalle_establecimiento_haz_join_y_responsable():
    from mcp_bd_readonly.tools_catalogo import detalle_establecimiento

    class FakeExRows:
        def __init__(self):
            self.rows = [{
                "id": 668, "nombre": "KIKO MILANO - SPAIN",
                "codigo": "P26/00299", "direccion_1": "CC Espai Gironès",
                "poblacion": "SALT", "provincia": "GIRONA", "codigo_postal": "17190",
                "telefono": "34972 43 92 46", "correo": "x@kiko.com", "observaciones": None,
                "responsable": "Maria Prat - Optima Retail (EQ4)", "cliente": "KIKO RETAIL ESPAÑA SLU",
            }]

        def run(self, sql, params=None, limit=100):
            if "COUNT(*)" in sql:
                return ["n"], [{"n": 1}]
            return ["id"], self.rows

    out = detalle_establecimiento(FakeExRows(), "kiko")
    assert out["n_encontrados"] == 1
    assert out["devueltos"] == 1
    e = out["establecimientos"][0]
    assert e["responsable"] == "Maria Prat - Optima Retail (EQ4)"
    assert e["cliente"] == "KIKO RETAIL ESPAÑA SLU"
    assert e["codigo"] == "P26/00299"
    assert e["direccion"] == "CC Espai Gironès, SALT, GIRONA"


def test_detalle_establecimiento_paginacion():
    from mcp_bd_readonly.tools_catalogo import _filter_establecimiento

    class FakeExRows:
        def __init__(self):
            self.sqls = []
            self.params = []

        def run(self, sql, params=None, limit=100):
            self.sqls.append(sql)
            self.params.append(list(params or []))
            if "COUNT(*)" in sql:
                return ["n"], [{"n": 43}]
            return ["id"], [{"id": i, "nombre": f"N{i}", "codigo": f"C{i}", "direccion_1": None,
                             "poblacion": None, "provincia": None, "codigo_postal": None,
                             "telefono": None, "correo": None, "observaciones": None,
                             "responsable": None, "cliente": None} for i in range(2)]

    ex = FakeExRows()
    n_total, rows = _filter_establecimiento(ex, "nike", max_n=2, offset=4)
    assert n_total == 43
    assert len(rows) == 2
    assert ex.params[0] == ["%nike%", "%nike%", "%nike%", "%nike%"]
    assert ex.params[1] == ["%nike%", "%nike%", "%nike%", "%nike%", 2, 4]
    select = ex.sqls[1]
    assert select.index("ORDER BY e.nombre") < select.index("LIMIT %s OFFSET %s")
    assert "LIMIT %s OFFSET %s" in select


def test_detalle_establecimiento_filtra_nulos():
    from mcp_bd_readonly.tools_catalogo import _filter_establecimiento

    class FakeExRows:
        def __init__(self):
            self.sql = None

        def run(self, sql, params=None, limit=100):
            self.sql = sql
            return ["id"], []

    ex = FakeExRows()
    _filter_establecimiento(ex, "nope")
    assert "deleted_at IS NULL" in ex.sql
    assert "LEFT JOIN users" in ex.sql
    assert "LEFT JOIN clientes" in ex.sql


def test_detalle_establecimiento_valida_max_n_y_offset():
    from mcp_bd_readonly.tools_catalogo import detalle_establecimiento
    import pytest

    class FakeExRows:
        def run(self, sql, params=None, limit=100):
            return ["n"], [{"n": 0}]

    for bad_max in (0, -1, True):
        with pytest.raises(ValueError) as ei:
            detalle_establecimiento(FakeExRows(), "x", max_n=bad_max)
        assert "max_n" in str(ei.value)
    for bad_off in (-1, -5):
        with pytest.raises(ValueError) as ei:
            detalle_establecimiento(FakeExRows(), "x", offset=bad_off)
        assert "offset" in str(ei.value)
