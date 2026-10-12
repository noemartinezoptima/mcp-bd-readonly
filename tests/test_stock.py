from mcp_bd_readonly.tools_stock import (
    build_stock_tools,
    movimientos_stock,
    stock_actual,
    stock_por_ubicacion,
)


class FakeEx:
    def __init__(self, stock_rows=None, mov_rows=None):
        self.stock_rows = stock_rows or []
        self.mov_rows = mov_rows or []
        self.calls = []

    def run(self, sql, params=None, limit=100):
        self.calls.append((sql, params, limit))
        if "stock_article_locations" in sql:
            return (
                ["article_id", "name", "barcode", "location_id", "ubicacion", "stock"],
                self.stock_rows,
            )
        if "FROM stock_locations" in sql:
            return ["ubicacion", "total"], [
                {"ubicacion": "Interno", "total": 100},
                {"ubicacion": "Externo", "total": 20},
            ]
        if "FROM stock_movements" in sql:
            return (
                ["article_id", "name", "ubicacion", "quantity", "resulting_stock", "stock_subtype_id", "created_at"],
                self.mov_rows,
            )
        return [], []


def test_stock_actual():
    ex = FakeEx(stock_rows=[
        {"article_id": 1, "name": "Arandela", "barcode": "123", "location_id": 1, "ubicacion": "Interno", "stock": 50},
    ])
    r = stock_actual(ex, max_n=200)
    assert r["stock"][0]["articulo"] == "Arandela"
    assert r["stock"][0]["stock"] == 50
    assert r["stock"][0]["ubicacion"] == "Interno"
    assert r["limit_aplicado"] == 200


def test_stock_actual_filtros():
    ex = FakeEx([])
    stock_actual(ex, location_id=2, articulo="tornillo", max_n=10)
    sql, params, _ = ex.calls[0]
    assert "sal.location_id = %s" in sql
    assert "sa.name LIKE %s" in sql
    assert params == [2, "%tornillo%", 10]


def test_stock_por_ubicacion():
    ex = FakeEx([])
    r = stock_por_ubicacion(ex)
    assert r["por_ubicacion"][0]["ubicacion"] == "Interno"
    assert r["por_ubicacion"][0]["total"] == 100


def test_movimientos_stock():
    ex = FakeEx(mov_rows=[
        {"article_id": 1, "name": "Arandela", "ubicacion": "Interno", "quantity": 10,
         "resulting_stock": 50, "stock_subtype_id": 3, "created_at": "2026-08-18 11:00:36"},
    ])
    r = movimientos_stock(ex, article_id=1, max_n=100)
    m = r["movimientos"][0]
    assert m["articulo"] == "Arandela"
    assert m["cantidad"] == 10
    assert m["stock_resultante"] == 50
    assert m["stock_subtype_id"] == 3


def test_build_stock_tools_registers_three():
    tools = build_stock_tools(executor=None, audit=None)
    names = {t.__name__ for t in tools}
    assert names == {"stock_actual", "stock_por_ubicacion", "movimientos_stock"}
