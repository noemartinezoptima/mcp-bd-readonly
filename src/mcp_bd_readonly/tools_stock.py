"""Tools de inventario / stock.

Modelo real: stock_articles (productos), stock_locations (ubicaciones),
stock_movements (movimientos con resulting_stock = stock tras el movimiento),
stock_article_locations (asignación artículo↔ubicación).

Stock actual = último resulting_stock por (article_id, location_id), vía
ROW_NUMBER() sobre created_at DESC. Artículos asignados sin movimientos = stock 0.
"""

from mcp_bd_readonly.db import QueryExecutor
from mcp_bd_readonly.audit import AuditLogger

_ULTIMO_STOCK = (
    "SELECT article_id, location_id, resulting_stock, "
    "ROW_NUMBER() OVER (PARTITION BY article_id, location_id "
    "ORDER BY created_at DESC, id DESC) rn FROM stock_movements"
)


def stock_actual(ex, location_id=None, articulo=None, max_n: int = 200):
    """Stock actual por artículo + ubicación (último resulting_stock)."""
    where = "1=1"
    params = []
    if location_id:
        where += " AND sal.location_id = %s"
        params.append(location_id)
    if articulo:
        where += " AND sa.name LIKE %s"
        params.append(f"%{articulo}%")
    sql = (
        "SELECT sa.id article_id, sa.name, sa.barcode, sl.id location_id, sl.name ubicacion, "
        "COALESCE(sm.resulting_stock, 0) stock "
        "FROM stock_article_locations sal "
        "JOIN stock_articles sa ON sa.id = sal.article_id AND sa.deleted_at IS NULL "
        "JOIN stock_locations sl ON sl.id = sal.location_id AND sl.deleted_at IS NULL "
        f"LEFT JOIN ({_ULTIMO_STOCK}) sm "
        "ON sm.article_id = sal.article_id AND sm.location_id = sal.location_id AND sm.rn = 1 "
        f"WHERE {where} ORDER BY stock DESC LIMIT %s"
    )
    _, rows = ex.run(sql, params + [int(max_n)], limit=None)
    out = [
        {
            "article_id": r["article_id"],
            "articulo": r["name"],
            "barcode": r["barcode"],
            "location_id": r["location_id"],
            "ubicacion": r["ubicacion"],
            "stock": r["stock"],
        }
        for r in rows
    ]
    return {"stock": out, "limit_aplicado": int(max_n)}


def stock_por_ubicacion(ex):
    """Total de stock actual agrupado por ubicación."""
    sql = (
        "SELECT sl.name ubicacion, COALESCE(SUM(sm.resulting_stock),0) total "
        f"FROM stock_locations sl LEFT JOIN ({_ULTIMO_STOCK}) sm "
        "ON sm.location_id = sl.id AND sm.rn = 1 "
        "WHERE sl.deleted_at IS NULL GROUP BY sl.id, sl.name ORDER BY total DESC"
    )
    _, rows = ex.run(sql, limit=None)
    return {"por_ubicacion": [{"ubicacion": r["ubicacion"], "total": r["total"]} for r in rows]}


def movimientos_stock(ex, article_id=None, max_n: int = 100):
    """Historial de movimientos de stock (últimos primero), opcional por artículo."""
    where = "1=1"
    params = []
    if article_id:
        where += " AND sm.article_id = %s"
        params.append(article_id)
    sql = (
        "SELECT sm.article_id, sa.name, sm.location_id, sl.name ubicacion, "
        "sm.quantity, sm.resulting_stock, sm.stock_subtype_id, sm.created_at "
        "FROM stock_movements sm "
        "JOIN stock_articles sa ON sa.id = sm.article_id "
        "JOIN stock_locations sl ON sl.id = sm.location_id "
        f"WHERE {where} ORDER BY sm.created_at DESC LIMIT %s"
    )
    _, rows = ex.run(sql, params + [int(max_n)], limit=None)
    out = [
        {
            "article_id": r["article_id"],
            "articulo": r["name"],
            "ubicacion": r["ubicacion"],
            "cantidad": r["quantity"],
            "stock_resultante": r["resulting_stock"],
            "stock_subtype_id": r["stock_subtype_id"],
            "fecha": str(r["created_at"]),
        }
        for r in rows
    ]
    return {"movimientos": out}


def build_stock_tools(executor: QueryExecutor, audit: AuditLogger):

    def _tool(name, doc):
        def wrap(fn):
            fn.__name__ = name
            fn.__doc__ = doc
            return fn
        return wrap

    @_tool("stock_actual", "Stock actual por artículo + ubicación (último resulting_stock). Filtros: location_id, articulo (nombre).")
    def tool_stock_actual(location_id: int | None = None, articulo: str | None = None, max_n: int = 200):
        audit and audit.record("stock_actual", "mcp", "stock_actual")
        return stock_actual(executor, location_id, articulo, max_n)

    @_tool("stock_por_ubicacion", "Total de stock actual agrupado por ubicación (almacén).")
    def tool_stock_por_ubicacion():
        audit and audit.record("stock_por_ubicacion", "mcp", "stock_por_ubicacion")
        return stock_por_ubicacion(executor)

    @_tool("movimientos_stock", "Historial de movimientos de stock (últimos primero), opcional por article_id.")
    def tool_movimientos_stock(article_id: int | None = None, max_n: int = 100):
        audit and audit.record("movimientos_stock", "mcp", "movimientos_stock")
        return movimientos_stock(executor, article_id, max_n)

    return [tool_stock_actual, tool_stock_por_ubicacion, tool_movimientos_stock]
